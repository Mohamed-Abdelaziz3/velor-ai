'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const { after, before, test } = require('node:test');

const TEST_SECRET = 'phase3a-gateway-auth-test-secret-0123456789';
const COMPANY_ID = 'phase3a-company';

let backendServer;
let gatewayServer;
let gatewayPort;
let backendPort;
let sentMessages;
let acknowledgements;
let gateway;

function listen(server) {
    return new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(0, '127.0.0.1', () => {
            server.removeListener('error', reject);
            resolve(server.address().port);
        });
    });
}

function close(server) {
    return new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
    });
}

function request({ method, path, headers = {}, body, stream = false }) {
    return new Promise((resolve, reject) => {
        const req = http.request(
            {
                hostname: '127.0.0.1',
                port: gatewayPort,
                method,
                path,
                headers,
            },
            (res) => {
                const chunks = [];
                if (stream) {
                    const result = { status: res.statusCode, headers: res.headers, body: '' };
                    res.destroy();
                    resolve(result);
                    return;
                }
                res.on('data', (chunk) => chunks.push(chunk));
                res.on('end', () => {
                    resolve({
                        status: res.statusCode,
                        headers: res.headers,
                        body: Buffer.concat(chunks).toString('utf8'),
                    });
                });
            },
        );
        req.once('error', reject);
        if (body) req.write(body);
        req.end();
    });
}

before(async () => {
    sentMessages = [];
    acknowledgements = [];
    backendServer = http.createServer((req, res) => {
        if (req.method === 'GET' && req.url === `/api/internal/companies/${COMPANY_ID}/exists`) {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ success: true, exists: true }));
            return;
        }
        if (req.method === 'POST' && req.url === '/api/whatsapp/webhook/ack') {
            const chunks = [];
            req.on('data', (chunk) => chunks.push(chunk));
            req.on('end', () => {
                acknowledgements.push(JSON.parse(Buffer.concat(chunks).toString('utf8')));
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ success: true }));
            });
            return;
        }
        res.writeHead(404).end();
    });
    backendPort = await listen(backendServer);

    process.env.NODE_INTERNAL_SECRET = TEST_SECRET;
    process.env.AUTO_BOOT_SESSIONS = 'false';
    process.env.LOG_LEVEL = 'silent';
    process.env.BACKEND_CHAT_URL = `http://127.0.0.1:${backendPort}/chat`;
    gateway = require('../whatsapp_gate');
    gateway.sessions[COMPANY_ID] = {
        sendMessage: async (jid, payload) => {
            sentMessages.push({ jid, payload });
            return { key: { id: 'phase3a-provider-message-id' } };
        },
    };
    gateway.qrCodes[COMPANY_ID] = { status: 'connected', qr: '' };
    gatewayServer = http.createServer(gateway.app);
    gatewayPort = await listen(gatewayServer);
});

after(async () => {
    await close(gatewayServer);
    await close(backendServer);
});

test('all QR control routes reject requests without the internal secret', async () => {
    const cases = [
        { method: 'GET', path: `/api/whatsapp/stream/${COMPANY_ID}`, stream: true },
        { method: 'GET', path: `/api/whatsapp/status/${COMPANY_ID}` },
        { method: 'POST', path: `/api/whatsapp/start/${COMPANY_ID}` },
        {
            method: 'POST',
            path: `/api/whatsapp/send/${COMPANY_ID}`,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone: '201000000000', message: 'test' }),
        },
    ];

    const responses = await Promise.all(cases.map((item) => request(item)));
    assert.deepEqual(responses.map((response) => response.status), [401, 401, 401, 401]);
});

test('all QR control routes accept an authorized request', async () => {
    const auth = { 'X-Internal-Secret': TEST_SECRET };
    const stream = await request({
        method: 'GET',
        path: `/api/whatsapp/stream/${COMPANY_ID}`,
        headers: auth,
        stream: true,
    });
    const status = await request({
        method: 'GET',
        path: `/api/whatsapp/status/${COMPANY_ID}`,
        headers: auth,
    });
    const start = await request({
        method: 'POST',
        path: `/api/whatsapp/start/${COMPANY_ID}`,
        headers: auth,
    });
    const send = await request({
        method: 'POST',
        path: `/api/whatsapp/send/${COMPANY_ID}`,
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: '201000000000', message: 'test', internal_message_id: 'phase3a-internal-id' }),
    });

    assert.deepEqual([stream.status, status.status, start.status, send.status], [200, 200, 200, 200]);
    assert.match(String(stream.headers['content-type']), /text\/event-stream/);
    assert.equal(JSON.parse(status.body).status, 'connected');
    assert.equal(JSON.parse(start.body).status, 'already_running');
    assert.equal(JSON.parse(send.body).success, true);
    assert.equal(sentMessages.length, 1);
    assert.equal(acknowledgements.length, 1);
});

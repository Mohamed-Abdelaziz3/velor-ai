require('dotenv').config();

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const EventEmitter = require('events');

const axios = require('axios');
const cors = require('cors');
const express = require('express');
const pino = require('pino');
const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion,
    jidDecode,
} = require('@whiskeysockets/baileys');

const QRCode = require('qrcode');
const logger = pino({ level: process.env.LOG_LEVEL || 'warn' });
const app = express();
const waEvents = new EventEmitter();
waEvents.setMaxListeners(0);

const PORT = process.env.NODE_PORT || 3005;
const HOST = String(process.env.NODE_HOST || '127.0.0.1').trim();
const RUNTIME_ENV = String(process.env.ENV || process.env.NODE_ENV || 'development').trim().toLowerCase();
const ALLOWED_FRONTEND = (process.env.ALLOWED_FRONTEND || 'http://localhost:5173')
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
const INTERNAL_SECRET = process.env.NODE_INTERNAL_SECRET || '';
const RELEASE_ENVIRONMENTS = new Set(['verification', 'staging', 'production', 'release']);
const WEAK_INTERNAL_SECRETS = new Set([
    'secret',
    'changeme',
    'change-me',
    'change_me',
    'default',
    'development',
    'test',
    'node-internal-secret',
    'super-secret-test-key-32-chars-long',
]);

function isWeakInternalSecret(value) {
    const secret = String(value || '').trim();
    const normalized = secret.toLowerCase();
    return secret.length < 32
        || WEAK_INTERNAL_SECRETS.has(normalized)
        || /(change-?me|replace-?me|your-?secret|example|default|test-?secret)/.test(normalized)
        || /^(.{1,8})\1+$/.test(secret);
}

if (RELEASE_ENVIRONMENTS.has(RUNTIME_ENV) && isWeakInternalSecret(INTERNAL_SECRET)) {
    throw new Error('NODE_INTERNAL_SECRET must be a unique non-placeholder secret of at least 32 characters in release environments');
}

function normalizeChatUrl(value) {
    const raw = String(value || '').trim();
    if (!raw) return 'http://127.0.0.1:8000/chat';
    return raw.endsWith('/chat') ? raw : `${raw.replace(/\/+$/, '')}/chat`;
}

const BACKEND_CHAT_URL = normalizeChatUrl(process.env.BACKEND_CHAT_URL || process.env.API_URL);
const SESSIONS_DIR = path.join(__dirname, 'sessions');
const AUTO_BOOT_SESSIONS = (process.env.AUTO_BOOT_SESSIONS || 'true') !== 'false';
const AUTO_BOOT_DELAY_MS = Number(process.env.AUTO_BOOT_DELAY_MS || 1500);
const SEND_TIMEOUT_MS = Number(process.env.WHATSAPP_SEND_TIMEOUT_MS || 15000);

const sessions = Object.create(null);
const qrCodes = Object.create(null);
const circuitBreaker = Object.create(null);
const processedMessages = new Set();
const staleSessions = Object.create(null);
const deliveryAttempts = [];
const LONG_MESSAGE_REPLY = '\u0639\u0641\u0648\u0627\u060c \u0627\u0644\u0631\u0633\u0627\u0644\u0629 \u0637\u0648\u064a\u0644\u0629 \u062c\u062f\u0627\u060c \u0645\u0645\u0643\u0646 \u062a\u0644\u062e\u0635\u0647\u0627\u061f';
const TECHNICAL_FALLBACK_REPLY = '\u0639\u0630\u0631\u0627\u064b\u060c \u0627\u0644\u0646\u0638\u0627\u0645 \u064a\u0648\u0627\u062c\u0647 \u0636\u063a\u0637\u0627\u064b \u062a\u0642\u0646\u064a\u0627\u064b \u062d\u0627\u0644\u064a\u0627\u064b. \u064a\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0628\u0639\u062f \u0642\u0644\u064a\u0644.';

const CB_FAIL_THRESHOLD = 3;
const CB_TIMEOUT_MS = 30000;
const MAX_PROCESSED_MESSAGES = 2000;

app.use(cors({
    origin: ALLOWED_FRONTEND,
    credentials: true,
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'X-Internal-Secret'],
}));
app.use(express.json({ limit: '10kb' }));

// Request logger: prints every incoming HTTP request for debugging.
app.use((req, res, next) => {
    const start = Date.now();
    res.on('finish', () => {
        const ms = Date.now() - start;
        console.log(`[${new Date().toISOString()}] ${req.method} ${req.originalUrl} -> ${res.statusCode} (${ms}ms)`);
    });
    next();
});

function isValidCompanyId(companyId) {
    return Boolean(companyId && /^[\w-]{1,64}$/.test(companyId));
}

function safeEqual(a, b) {
    const left = Buffer.from(String(a || ''));
    const right = Buffer.from(String(b || ''));
    return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function errorType(error) {
    return error && error.name ? String(error.name) : 'Error';
}

function requireInternalSecret(req, res, next) {
    if (!INTERNAL_SECRET) {
        return res.status(503).json({ success: false, message: 'Gateway internal secret is not configured' });
    }
    if (!safeEqual(req.get('X-Internal-Secret'), INTERNAL_SECRET)) {
        return res.status(401).json({ success: false, message: 'Unauthorized gateway request' });
    }
    return next();
}

function rememberMessage(id) {
    if (!id) return false;
    if (processedMessages.has(id)) return true;
    processedMessages.add(id);
    if (processedMessages.size > MAX_PROCESSED_MESSAGES) {
        const first = processedMessages.values().next().value;
        processedMessages.delete(first);
    }
    return false;
}

function toWhatsAppJid(raw) {
    const value = String(raw || '').trim();
    if (!value) throw new Error('Missing phone/JID');

    if (value.includes('@s.whatsapp.net') || value.includes('@g.us') || value.includes('@lid')) {
        const decoded = jidDecode(value);
        if (!decoded || !decoded.user) {
            throw new Error(`Invalid JID: ${value}`);
        }
        return value;
    }

    let digits = value.replace(/\D/g, '');
    if (!digits) throw new Error('Missing phone digits');

    if (digits.startsWith('01') && digits.length === 11) {
        digits = `2${digits}`;
    } else if (digits.startsWith('1') && digits.length === 10) {
        digits = `20${digits}`;
    }

    return `${digits}@s.whatsapp.net`;
}

function publishCompanyState(companyId, state) {
    qrCodes[companyId] = state;
    waEvents.emit(`update-${companyId}`, state);
}

function backendBaseUrl() {
    return BACKEND_CHAT_URL.replace(/\/chat$/, '');
}

async function validateCompanySession(companyId) {
    if (!INTERNAL_SECRET) {
        const state = { qr: '', status: 'stale', reason: 'missing_internal_secret' };
        staleSessions[companyId] = state;
        publishCompanyState(companyId, state);
        logger.warn({ companyId }, 'Skipping saved session because NODE_INTERNAL_SECRET is missing');
        return false;
    }

    const response = await axios.get(`${backendBaseUrl()}/api/internal/companies/${encodeURIComponent(companyId)}/exists`, {
        headers: { 'X-Internal-Secret': INTERNAL_SECRET },
        timeout: 5000,
        validateStatus: (status) => status < 500,
    });

    if (response.status === 200 && response.data?.exists === true) {
        delete staleSessions[companyId];
        return true;
    }

    const reason = response.status === 404 ? 'company_not_found' : `validation_status_${response.status}`;
    const state = { qr: '', status: 'stale', reason };
    staleSessions[companyId] = state;
    publishCompanyState(companyId, state);
    logger.warn({ companyId, status: response.status }, 'Skipping stale saved WhatsApp session');
    return false;
}

function rememberDeliveryAttempt(entry) {
    deliveryAttempts.push({
        ts: new Date().toISOString(),
        ...entry,
    });
    while (deliveryAttempts.length > 100) {
        deliveryAttempts.shift();
    }
}

function withTimeout(promise, timeoutMs, label) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function pushAck(companyId, internalMessageId, waMessageId, status) {
    try {
        if (!waMessageId && !internalMessageId) return;
        const baseUrl = BACKEND_CHAT_URL.replace('/chat', '');
        await axios.post(`${baseUrl}/api/whatsapp/webhook/ack`, {
            company_id: companyId,
            internal_message_id: internalMessageId,
            wa_message_id: waMessageId,
            status: status
        }, {
            headers: { 'X-Internal-Secret': INTERNAL_SECRET }
        });
    } catch (err) {
        logger.warn({ companyId, waMessageId, errorType: errorType(err) }, 'Failed to push ACK');
    }
}

async function sendAndAck(sock, companyId, jid, text, internalMessageId) {
    rememberDeliveryAttempt({
        company_id: companyId,
        jid,
        internal_message_id: internalMessageId || null,
        status: 'attempting',
    });
    try {
        const sentMsg = await withTimeout(sock.sendMessage(jid, { text }), SEND_TIMEOUT_MS, `WhatsApp send to ${jid}`);
        rememberDeliveryAttempt({
            company_id: companyId,
            jid,
            internal_message_id: internalMessageId || null,
            wa_message_id: sentMsg?.key?.id || null,
            status: 'sent',
        });
        if (internalMessageId) {
            const baseUrl = BACKEND_CHAT_URL.replace('/chat', '');
            await axios.post(`${baseUrl}/api/whatsapp/webhook/ack`, {
                company_id: companyId,
                internal_message_id: internalMessageId,
                wa_message_id: sentMsg?.key?.id,
                status: 'sent'
            }, {
                headers: { 'X-Internal-Secret': INTERNAL_SECRET }
            }).catch(err => {
                logger.warn({ companyId, errorType: errorType(err) }, 'Failed to send ACK to backend');
            });
        }
        return sentMsg;
    } catch (err) {
        logger.error({ companyId, errorType: errorType(err) }, 'sendAndAck failed to send message');
        rememberDeliveryAttempt({
            company_id: companyId,
            jid,
            internal_message_id: internalMessageId || null,
            status: 'failed',
            error: err.message,
        });
        if (internalMessageId) {
            await pushAck(companyId, internalMessageId, null, 'failed');
        }
        throw err;
    }
}

async function fetchAIWithRetry(companyId, payload, retries = 3) {
    if (!INTERNAL_SECRET) {
        throw new Error('NODE_INTERNAL_SECRET is missing');
    }

    if (!circuitBreaker[companyId]) {
        circuitBreaker[companyId] = { failures: 0, state: 'CLOSED', unlockTime: 0 };
    }
    const cb = circuitBreaker[companyId];

    if (cb.state === 'OPEN') {
        if (Date.now() > cb.unlockTime) {
            cb.state = 'HALF_OPEN';
        } else {
            throw new Error(`Circuit breaker open for ${companyId}`);
        }
    }

    for (let i = 0; i < retries; i += 1) {
        try {
            const response = await axios.post(BACKEND_CHAT_URL, payload, {
                headers: {
                    'X-Internal-Secret': INTERNAL_SECRET,
                    'X-Company-ID': companyId,
                },
                timeout: 45000,
                validateStatus: (status) => status < 500 || status === 500 || status === 429
            });
            
            if (response.status === 401 || response.status === 403 || response.status === 404) {
                logger.warn({ companyId, status: response.status }, 'Ghost session or unauthorized company detected. Ignoring message.');
                return { reply: null };
            }
            
            if (response.data && response.data.reply !== undefined) {
                cb.failures = 0;
                cb.state = 'CLOSED';
                return response.data;
            }
            
            throw new Error(`Invalid response from backend: ${response.status}`);
        } catch (error) {
            if (i === retries - 1) {
                cb.failures += 1;
                if (cb.failures >= CB_FAIL_THRESHOLD) {
                    cb.state = 'OPEN';
                    cb.unlockTime = Date.now() + CB_TIMEOUT_MS;
                    logger.warn({ companyId }, 'Circuit breaker opened');
                }
                throw error;
            }
            await new Promise((resolve) => setTimeout(resolve, 1000 * Math.pow(2, i)));
        }
    }
}

async function initializeCompany(companyId) {
    if (!isValidCompanyId(companyId)) {
        throw new Error('Invalid company id');
    }
    if (!(await validateCompanySession(companyId))) {
        return { alreadyRunning: false, stale: true };
    }
    if (sessions[companyId]) {
        console.log(`Session already running for ${companyId}; skipping init`);
        return { alreadyRunning: true };
    }

    fs.mkdirSync(SESSIONS_DIR, { recursive: true });
    publishCompanyState(companyId, { qr: '', status: 'initializing' });
    console.log(`Initializing WhatsApp session for ${companyId}...`);

    const { state, saveCreds } = await useMultiFileAuthState(path.join(SESSIONS_DIR, companyId));
    const { version } = await fetchLatestBaileysVersion();

    const sock = makeWASocket({
        version,
        logger,
        printQRInTerminal: false,
        auth: state,
        markOnlineOnConnect: false,
        generateHighQualityLinkPreview: false,
    });

    sessions[companyId] = sock;
    console.log(`Session stored for ${companyId}. Active sessions: [${Object.keys(sessions).join(', ')}]`);
    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        console.log(`[${companyId}] connection.update:`, JSON.stringify({ connection, hasQR: !!qr }));

        if (qr) {
            try {
                // Convert raw QR text to base64 PNG data URI for the frontend <img> tag
                const qrDataUri = await QRCode.toDataURL(qr, {
                    width: 320,
                    margin: 2,
                    color: { dark: '#000000', light: '#ffffff' },
                });
                publishCompanyState(companyId, { qr: qrDataUri, status: 'waiting_qr' });
            } catch (qrErr) {
                logger.error({ companyId, errorType: errorType(qrErr) }, 'QR code generation failed');
                publishCompanyState(companyId, { qr: '', status: 'waiting_qr' });
            }
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log(`[${companyId}] Connection closed. statusCode=${statusCode}, shouldReconnect=${shouldReconnect}`);
            publishCompanyState(companyId, { qr: '', status: 'disconnected' });

            if (shouldReconnect) {
                // Keep the session and its existing socket reference during reconnect.
                // until the reconnect replaces it. This prevents the "empty sessions" gap.
                console.log(`[${companyId}] Reconnecting in 5s (session kept in memory)...`);
                setTimeout(() => {
                    // Now clear the stale session right before reinitializing
                    delete sessions[companyId];
                    initializeCompany(companyId).catch((err) => {
                        console.error(`[${companyId}] Reconnect failed (${errorType(err)})`);
                        logger.error({ companyId, errorType: errorType(err) }, 'Reconnect failed');
                    });
                }, 5000);
            } else {
                // Permanent logout: delete the session from memory and disk.
                delete sessions[companyId];
                fs.rmSync(path.join(SESSIONS_DIR, companyId), { recursive: true, force: true });
                publishCompanyState(companyId, { qr: '', status: 'logged_out' });
                console.log(`[${companyId}] Permanently logged out; session deleted.`);
            }
        } else if (connection === 'open') {
            // Make sure the session is stored with the CURRENT sock reference
            sessions[companyId] = sock;
            publishCompanyState(companyId, { qr: '', status: 'connected' });
            console.log(`[${companyId}] WhatsApp connected. Active sessions: [${Object.keys(sessions).join(', ')}]`);
            logger.info({ companyId }, 'WhatsApp session connected');
        }
    });

        sock.ev.on('messages.update', async (updates) => {
        for (const update of updates) {
            const waId = update.key?.id;
            if (!waId) continue;
            
            let newStatus = null;
            if (update.update?.status === 2) newStatus = 'sent';
            else if (update.update?.status === 3) newStatus = 'delivered';
            else if (update.update?.status === 4) newStatus = 'read';
            
            if (newStatus) {
                await pushAck(companyId, null, waId, newStatus);
            }
        }
    });

    sock.ev.on('messages.upsert', async (m) => {
        const msg = m.messages?.[0];
        if (!msg?.message || msg.key?.fromMe) return;
        if (msg.key?.remoteJid?.includes('@g.us')) return;
        if (rememberMessage(`${companyId}:${msg.key?.id}`)) return;

        const text = msg.message.conversation || msg.message.extendedTextMessage?.text;
        if (!text || !text.trim()) return;

        const sender = msg.key.remoteJid;
        if (text.length > 800) {
            await sock.sendMessage(sender, { text: LONG_MESSAGE_REPLY });
            return;
        }
        if (text.length > 800) {
            await sock.sendMessage(sender, { text: 'عفوًا، الرسالة طويلة جدًا. ممكن تلخصها؟' });
            return;
        }

        let backendReplyReturned = false;
        try {
            // await sock.sendPresenceUpdate('composing', sender);
            const responseData = await fetchAIWithRetry(companyId, {
                message: text,
                user_id: sender,
                external_message_id: msg.key?.id,
            });

            if (responseData?.reply) {
                // await sock.sendPresenceUpdate('paused', sender);
                backendReplyReturned = true;
                rememberDeliveryAttempt({
                    company_id: companyId,
                    jid: sender,
                    internal_message_id: responseData.internal_message_id || null,
                    inbound_wa_message_id: msg.key?.id || null,
                    status: 'backend_reply_received',
                });
                await sendAndAck(sock, companyId, sender, responseData.reply, responseData.internal_message_id);
            } else {
                rememberDeliveryAttempt({
                    company_id: companyId,
                    jid: sender,
                    inbound_wa_message_id: msg.key?.id || null,
                    status: 'no_backend_reply',
                    reason: responseData?.reason || null,
                });
            }
        } catch (err) {
            if (backendReplyReturned) {
                logger.error({ companyId, waMessageId: msg.key?.id, errorType: errorType(err) }, 'Reply send failed after backend response; suppressing local fallback to avoid double reply');
                return;
            }
            logger.error({ companyId, waMessageId: msg.key?.id, errorType: errorType(err) }, 'Backend chat request failed');
            try {
                await sock.sendMessage(sender, { text: TECHNICAL_FALLBACK_REPLY });
            } catch (fallbackErr) {
                logger.error({ companyId, errorType: errorType(fallbackErr) }, 'Failed to send fallback message');
            }
            return;
            logger.error({ companyId, errorType: errorType(err) }, 'Message pipeline failed');
            try {
                await sock.sendMessage(sender, { text: 'عذرًا، النظام يواجه ضغطًا تقنيًا حاليًا. يرجى المحاولة بعد قليل.' });
            } catch (fallbackErr) {
                logger.error({ companyId, errorType: errorType(fallbackErr) }, 'Failed to send fallback message');
            }
        } finally {
            try { await sock.sendPresenceUpdate('paused', sender); } catch (e) {}
        }
    });

    return { alreadyRunning: false };
}

function loadExistingSessions() {
    if (!AUTO_BOOT_SESSIONS) {
        console.log('AUTO_BOOT_SESSIONS is disabled. No sessions will be loaded on startup.');
        console.log('   Set AUTO_BOOT_SESSIONS=true in .env or trigger /api/whatsapp/start/:company_id manually.');
        return;
    }
    fs.mkdirSync(SESSIONS_DIR, { recursive: true });

    const folders = fs.readdirSync(SESSIONS_DIR, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && isValidCompanyId(entry.name))
        .map((entry) => entry.name);

    console.log(`Auto-booting ${folders.length} saved session(s): [${folders.join(', ')}]`);

    folders.forEach((companyId, index) => {
        setTimeout(() => {
            console.log(`Auto-booting session: ${companyId}`);
            initializeCompany(companyId).catch((err) => {
                console.error(`Auto-boot failed for ${companyId} (${errorType(err)})`);
                logger.error({ companyId, errorType: errorType(err) }, 'Auto-boot failed');
            });
        }, index * AUTO_BOOT_DELAY_MS);
    });
}

app.use('/api/whatsapp', requireInternalSecret);

app.get('/api/whatsapp/stream/:company_id', (req, res) => {
    const { company_id } = req.params;
    if (!isValidCompanyId(company_id)) return res.status(400).send('Invalid ID');

    res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
    });

    const sendUpdate = (data) => {
        res.write(`data: ${JSON.stringify(data)}\n\n`);
    };

    sendUpdate(qrCodes[company_id] || { status: 'not_found', qr: null });

    const eventName = `update-${company_id}`;
    const heartbeat = setInterval(() => res.write(': ping\n\n'), 25000);
    waEvents.on(eventName, sendUpdate);

    req.on('close', () => {
        clearInterval(heartbeat);
        waEvents.removeListener(eventName, sendUpdate);
    });
});

app.get('/api/whatsapp/status/:company_id', (req, res) => {
    const { company_id } = req.params;
    if (!isValidCompanyId(company_id)) {
        return res.status(400).json({ success: false, message: 'Invalid ID' });
    }

    const data = qrCodes[company_id];
    if (!data) return res.json({ success: false, status: 'not_found' });
    return res.json({ success: true, status: data.status, qr_code: data.qr || null, reason: data.reason || null });
});

app.post('/api/whatsapp/start/:company_id', async (req, res) => {
    const { company_id } = req.params;
    if (!isValidCompanyId(company_id)) {
        return res.status(400).json({ success: false, message: 'Invalid ID' });
    }

    try {
        const result = await initializeCompany(company_id);
        if (result.stale) {
            return res.status(404).json({
                success: false,
                status: 'stale',
                message: `Saved session for ${company_id} does not match an active company`,
            });
        }
        return res.json({
            success: true,
            status: result.alreadyRunning ? 'already_running' : 'initializing',
            message: `Boot started for ${company_id}`,
        });
    } catch (err) {
        logger.error({ companyId: company_id, errorType: errorType(err) }, 'Boot failed');
        return res.status(500).json({ success: false, message: 'Failed to start WhatsApp session' });
    }
});

app.post('/api/whatsapp/send/:company_id', async (req, res) => {
    const { company_id } = req.params;
    const { phone, message } = req.body;
    
    if (!isValidCompanyId(company_id)) {
        return res.status(400).json({ success: false, message: 'Invalid ID' });
    }
    
    const sock = sessions[company_id];
    if (!sock) {
        return res.status(404).json({ success: false, message: 'WhatsApp session not found' });
    }
    
    try {
        const targetJid = toWhatsAppJid(req.body.jid || phone);

        await sendAndAck(sock, company_id, targetJid, message, req.body.internal_message_id);
        return res.json({ success: true, message: 'Alert sent successfully' });
    } catch (err) {
        logger.error({ companyId: company_id, errorType: errorType(err) }, 'Failed to send alert');
        return res.status(500).json({ success: false, message: 'Failed to send message' });
    }
});

// Takeover route (called by FastAPI agent_takeover).
app.post('/whatsapp/agent/takeover', requireInternalSecret, async (req, res) => {
    console.log('\nReceived takeover request');
    // console.log('Body:', JSON.stringify(req.body, null, 2)); // Removed to prevent logging customer data

    const { company_id, jid, phone, message, internal_message_id } = req.body;
    const rawNumber = jid || phone;

    // 1. Validate inputs
    if (!company_id || !isValidCompanyId(company_id)) {
        console.log('400: Invalid or missing company_id');
        return res.status(400).json({ success: false, error: 'Invalid or missing company_id' });
    }
    if (!rawNumber) {
        console.log('400: Missing jid or phone');
        return res.status(400).json({ success: false, error: 'Missing jid or phone in request body' });
    }
    if (!message) {
        console.log('400: Missing message');
        return res.status(400).json({ success: false, error: 'Missing message in request body' });
    }

    // 2. Check session exists
    const sock = sessions[company_id];
    if (!sock) {
        console.log(`404: No session for ${company_id}. Active: [${Object.keys(sessions).join(', ')}]`);
        return res.status(404).json({ success: false, error: 'No active WhatsApp session for ' + company_id });
    }

    let finalJid;
    try {
        finalJid = toWhatsAppJid(rawNumber);
    } catch (err) {
        console.log('400: Invalid phone or JID');
        return res.status(400).json({ success: false, error: 'Invalid phone or JID' });
    }

    // 4. Send message using the finalJid and wait for confirmation
    try {
        console.log(`Sending takeover message for company=${company_id}`);
        await sendAndAck(sock, company_id, finalJid, message, internal_message_id);
        console.log(`Takeover message delivered for company=${company_id}`);
        return res.status(200).json({ success: true, delivered_to: finalJid });
    } catch (err) {
        console.error(`Takeover send failed for company=${company_id} (${errorType(err)})`);
        return res.status(500).json({ success: false, error: 'Failed to send takeover message' });
    }
});

app.get('/', (req, res) => res.send('VELOR Gateway is running on port 3005'));

app.get('/api/debug/delivery/:company_id', requireInternalSecret, (req, res) => {
    const { company_id } = req.params;
    if (!isValidCompanyId(company_id)) {
        return res.status(400).json({ success: false, message: 'Invalid ID' });
    }

    return res.json({
        success: true,
        company_id,
        has_session: Boolean(sessions[company_id]),
        session_status: qrCodes[company_id]?.status || (sessions[company_id] ? 'connected' : 'missing'),
        send_timeout_ms: SEND_TIMEOUT_MS,
        attempts: deliveryAttempts.filter((entry) => entry.company_id === company_id).slice(-50),
    });
});

async function gracefulShutdown(signal) {
    logger.warn({ signal }, 'Shutting down');
    for (const cid of Object.keys(sessions)) {
        try {
            sessions[cid].ws?.close();
        } catch (e) {
            logger.warn({ companyId: cid, errorType: errorType(e) }, 'Session close failed');
        }
    }
    process.exit(0);
}

process.on('SIGINT', () => gracefulShutdown('SIGINT'));
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('uncaughtException', (err) => {
    logger.error({ errorType: errorType(err) }, 'Uncaught exception');
});
process.on('unhandledRejection', (reason) => {
    logger.error({ errorType: errorType(reason) }, 'Unhandled rejection');
});

app.listen(PORT, HOST, () => {
    console.log('\n============================================');
    console.log(`VELOR WhatsApp Gateway is listening on ${HOST}:${PORT}`);
    console.log('============================================\n');
    logger.warn(`Baileys Gateway running on ${HOST}:${PORT}`);
    loadExistingSessions();
});

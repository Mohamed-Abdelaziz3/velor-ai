import { createServer } from 'vite'
import { createViteOptions } from './vite-runtime.mjs'

const server = await createServer(await createViteOptions('development'))
await server.listen()
server.printUrls()

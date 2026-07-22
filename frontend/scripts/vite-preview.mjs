import { preview } from 'vite'
import { createViteOptions } from './vite-runtime.mjs'

const server = await preview(await createViteOptions('production'))
server.printUrls()

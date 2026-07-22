import { build } from 'vite'
import { createViteOptions } from './vite-runtime.mjs'

await build(await createViteOptions('production'))

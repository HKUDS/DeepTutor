import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';
import { z } from 'astro/zod';

// `quadrant` is the Diátaxis label for authors. The splash homepage omits it.
// Every other page sets exactly one of these values.
export const collections = {
	docs: defineCollection({
		loader: docsLoader(),
		schema: docsSchema({
			extend: z.object({
				quadrant: z.enum(['tutorial', 'how-to', 'reference', 'explanation']).optional(),
			}),
		}),
	}),
};

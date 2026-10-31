package gm.sample;

import gm.companion.api.ClientModule;
import gm.companion.api.ModuleContext;
import net.minecraft.client.Minecraft;

/**
 * Test module for spike S4. Draws a banner naming its generation, so a screenshot proves it ran.
 * Every 25th generation deliberately throws, to prove a broken module can't take the game down.
 */
public final class Banner implements ClientModule {
	private static final int BROKEN_EVERY = 25;

	private int ticks;

	@Override
	public void enable(ModuleContext context) {
		boolean broken = context.generation() % BROKEN_EVERY == 0;
		context.onClientTick(client -> this.ticks++);
		context.onHud((graphics, deltaTracker) -> {
			if (broken) {
				throw new IllegalStateException("deliberately broken generation " + context.generation());
			}
			graphics.fill(4, 4, 220, 22, 0xC0200040);
			graphics.text(Minecraft.getInstance().font,
					"hot-loaded module, generation " + context.generation(), 8, 9, 0xFFFFE080);
		});
	}
}

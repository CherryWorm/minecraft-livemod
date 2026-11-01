package gm.feature.german;

import gm.companion.api.ClientModule;
import gm.companion.api.ModuleContext;
import net.minecraft.client.Minecraft;

/** Test fixture: draws one of the feature's texts on the screen, which a client module says the same way a server one does. */
public final class GermanClient implements ClientModule {
	private static final int LEFT = 8;
	private static final int TOP = 8;
	private static final int WHITE = 0xFFFFFFFF;

	@Override
	public void enable(ModuleContext context) {
		context.onHud((graphics, deltaTracker) -> graphics.text(Minecraft.getInstance().font, context.text("hud"), LEFT, TOP, WHITE, true));
	}
}

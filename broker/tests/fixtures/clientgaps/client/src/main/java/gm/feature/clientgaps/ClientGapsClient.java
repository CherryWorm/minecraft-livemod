package gm.feature.clientgaps;

import gm.companion.api.ClientModule;
import gm.companion.api.KeyInput;
import gm.companion.api.ModuleContext;
import gm.companion.api.ModuleKey;
import gm.companion.api.WorldLook;

/** Test fixture: a bar as long as how many times its key has been pressed, and another while it's held, and each press shows a burst only this player sees. */
public final class ClientGapsClient implements ClientModule {
	private static final int GREEN = 0xFF00FF00;
	private static final int BLUE = 0xFF0000FF;
	private static final int STEP_OF_BAR = 8;
	private static final WorldLook SPECK = WorldLook.of(0xFF00FFFF);

	private int pressed;

	@Override
	public void enable(ModuleContext context) {
		ModuleKey act = context.key("act", KeyInput.of('Y'));
		act.onPressed(() -> {
			this.pressed++;
			context.showBurst(SPECK, 30.5, 123, 44, 100, 1, 0.2F, 0.2F, 7);
		});
		context.onHud((graphics, delta) -> {
			graphics.fill(4, 4, 4 + this.pressed * STEP_OF_BAR, 8, GREEN);
			if (act.isDown()) {
				graphics.fill(4, 12, 40, 16, BLUE);
			}
		});
	}
}

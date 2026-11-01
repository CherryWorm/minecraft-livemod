package gm.feature.worlddraw;

import gm.companion.api.ClientModule;
import gm.companion.api.KeyInput;
import gm.companion.api.ModuleContext;
import gm.companion.api.WorldCanvas;
import gm.companion.api.WorldLook;

/** Test fixture: draws one of every kind of thing at places broker/tests/world_draw_test.py knows, while a key has it turned on, and shakes the camera for another. */
public final class WorldDrawClient implements ClientModule {
	private static final int Z = 48;
	private static final WorldLook BOX = WorldLook.of(0x80FF00FF);
	private static final WorldLook EDGES = WorldLook.of(0xFF00FF00);
	private static final WorldLook RING = WorldLook.of(0xFFFFFFFF).image("ring");
	private static final WorldLook BEAM = WorldLook.of(0xFFFFFF00).glowing();
	private static final WorldLook SWIRL = WorldLook.of(0xFFFFFFFF).shader("swirl");
	private static final WorldLook GHOST = WorldLook.of(0x80FFFFFF);
	private static final WorldLook HIDDEN = WorldLook.of(0xFFFF0000);
	private static final WorldLook THROUGH = WorldLook.of(0xFF00FFFF).throughWalls();
	private static final WorldLook WARP = WorldLook.of(0xFFFFFFFF).shader("warp");
	private static final WorldLook MISSING = WorldLook.of(0xFFFFFFFF).shader("no_such_shader");

	private boolean on;

	@Override
	public void enable(ModuleContext context) {
		context.onKeyPressed(key -> {
			if (key.key() == KeyInput.of('J')) {
				this.on = !this.on;
			} else if (key.key() == KeyInput.of('K')) {
				context.shakeCamera(5, 6);
			}
		});
		context.onWorld(canvas -> {
			if (this.on) {
				draw(canvas);
			}
		});
	}

	private static void draw(WorldCanvas canvas) {
		canvas.box(BOX, 36, 121, Z, 38, 123, Z + 2);
		canvas.edges(EDGES, 33, 121, Z, 35, 123, Z + 2, 0.1F);
		canvas.sheet(RING, 32, 121, Z, -2, 0, 0, 0, 2, 0);
		canvas.beam(BEAM, 29, 121, Z, 29, 124, Z, 0.5F);
		canvas.billboard(SWIRL, 27, 122, Z, 2, 2);
		canvas.block(GHOST, 24, 121, Z, "minecraft:gold_block");
		// Behind the stone wall the test builds, one that should be hidden and one that shouldn't.
		canvas.box(HIDDEN, 36, 125, Z, 37, 126, Z + 1);
		canvas.box(THROUGH, 33, 125, Z, 34, 126, Z + 1);
		canvas.sheet(WARP, 30, 124.5, Z, -4, 0, 0, 0, 3, 0);
		// A shader that isn't there has to cost nothing but itself.
		canvas.billboard(MISSING, 24, 126, Z, 1, 1);
	}
}

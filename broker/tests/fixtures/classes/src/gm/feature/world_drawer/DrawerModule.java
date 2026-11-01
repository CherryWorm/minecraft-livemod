package gm.feature.world_drawer;

import gm.companion.api.ClientModule;
import gm.companion.api.ModuleContext;
import gm.companion.api.WorldCanvas;
import gm.companion.api.WorldLook;

/** What a real module drawing in the world does, with nothing of the game's rendering in reach. */
public final class DrawerModule implements ClientModule {
	private static final WorldLook LOOK = WorldLook.of(0x80FF8800).image("ring").shader("shimmer").glowing().throughWalls();

	@Override
	public void enable(ModuleContext context) {
		context.onWorld(this::draw);
		context.shakeCamera(1, 1);
	}

	private void draw(WorldCanvas canvas) {
		double x = canvas.cameraX();
		double y = canvas.cameraY();
		double z = canvas.cameraZ();
		canvas.box(LOOK, x, y, z, x + 1, y + 1, z + 1);
		canvas.edges(LOOK, x, y, z, x + 1, y + 1, z + 1, 0.1F);
		canvas.sheet(LOOK, x, y, z, 1, 0, 0, 0, 1, 0);
		canvas.beam(LOOK, x, y, z, x, y + 10, z, 0.5F);
		canvas.billboard(LOOK, x, y, z, 1, 1);
		canvas.block(LOOK, 0, 64, 0, "minecraft:stone");
		canvas.block(LOOK, 0, 64, 0, 1);
	}
}

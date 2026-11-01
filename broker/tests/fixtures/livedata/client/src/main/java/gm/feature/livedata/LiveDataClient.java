package gm.feature.livedata;

import gm.companion.api.ClientModule;
import gm.companion.api.KeyInput;
import gm.companion.api.ModuleContext;
import gm.companion.api.ModuleImage;
import gm.companion.api.WorldView;
import net.minecraft.client.Minecraft;

/**
 * Test fixture: squares showing what the server last said, a real map of the land around the player, a picture it painted itself turned on its
 * side, and bars as long as which way they face and how many values they've heard, all at places broker/tests/live_data_test.py knows.
 */
public final class LiveDataClient implements ClientModule {
	private static final int MAP = 64;
	private static final int EVERY_TICKS = 10;
	private static final int WHITE = 0xFFFFFFFF;
	private static final int GREEN = 0xFF00FF00;
	private static final int BLUE = 0xFF0000FF;
	private static final int RED = 0xFFFF0000;
	private static final int ARROW = 16;
	private static final int TOO_BIG = 1024;
	private static final int BARS_FROM = 176;
	private static final int STEP_OF_BAR = 4;

	private final int[] colours = new int[MAP * MAP];
	private ModuleImage map;
	private ModuleImage arrow;
	private WorldView world;
	private int colour = 0xFF000000;
	private int late = 0xFF000000;
	private String said = "nothing";
	private int heard;
	private int ticks;
	private boolean refused;
	private boolean listening;

	@Override
	public void enable(ModuleContext context) {
		this.world = context.world();
		this.map = context.newImage(MAP, MAP);
		this.arrow = context.newImage(ARROW, ARROW);
		for (int y = 0; y < ARROW; y++) {
			for (int x = 0; x < ARROW; x++) {
				this.arrow.setPixel(x, y, x < ARROW / 2 ? BLUE : RED);
			}
		}
		this.arrow.upload();
		this.refused = refusesImages(context);
		context.onServerValue("colour", value -> {
			this.heard++;
			this.said = value;
			this.colour = 0xFF000000 | Integer.parseInt(value, 16);
		});
		// Only starts listening for this one when told to, by which time the value has arrived.
		context.onKeyPressed(key -> {
			if (key.key() == KeyInput.of('J') && !this.listening) {
				this.listening = true;
				context.onServerValue("late", value -> this.late = 0xFF000000 | Integer.parseInt(value, 16));
			}
		});
		context.onClientTick(client -> {
			if (this.ticks++ % EVERY_TICKS == 0 && this.world.inWorld()) {
				int x = (int) Math.floor(this.world.playerX()) - MAP / 2;
				int z = (int) Math.floor(this.world.playerZ()) - MAP / 2;
				this.world.readMap(x, z, MAP, MAP, 1, this.colours);
				this.map.setPixels(this.colours);
				this.map.upload();
			}
		});
		context.onHud((graphics, delta) -> {
			var font = Minecraft.getInstance().font;
			graphics.fill(4, 4, 36, 36, this.colour);
			graphics.fill(4, 40, 36, 72, this.late);
			this.map.draw(graphics, 40, 4, MAP * 2, MAP * 2);
			graphics.fill(BARS_FROM, 4, BARS_FROM + Math.max(0, (int) (this.world.yaw() + 180) / 2), 8, GREEN);
			graphics.fill(BARS_FROM, 12, BARS_FROM + this.heard * STEP_OF_BAR, 16, GREEN);
			this.arrow.drawTurned(graphics, BARS_FROM, 30, 32, 32, 90);
			if (this.refused) {
				graphics.fill(BARS_FROM, 20, BARS_FROM + 8, 24, GREEN);
			}
			int x = (int) Math.floor(this.world.playerX());
			int y = (int) Math.floor(this.world.playerY());
			int z = (int) Math.floor(this.world.playerZ());
			graphics.text(font, this.said + " at " + x + " " + y + " " + z + " facing " + (int) this.world.yaw() + " " + (int) this.world.pitch(), 4, 136, WHITE, true);
			graphics.text(font, this.world.dimension() + " " + this.world.biome(x, y, z) + " top " + this.world.surfaceY(x, z) + " day " + this.world.dayTime() + (this.world.isRaining() ? " rain" : " dry"), 4, 148, WHITE, true);
			graphics.text(font, "under " + this.world.blockName(x, y - 1, z) + " light " + this.world.lightLevel(x, y, z) + " loaded " + this.world.isLoaded(x, z), 4, 160, WHITE, true);
		});
	}

	private static boolean refusesImages(ModuleContext context) {
		try {
			context.newImage(TOO_BIG, TOO_BIG);
			return false;
		} catch (IllegalArgumentException expected) {
			// Two here already, so two more is the most, and the one after that isn't allowed.
			context.newImage(1, 1);
			context.newImage(1, 1);
			try {
				context.newImage(1, 1);
				return false;
			} catch (IllegalStateException alsoExpected) {
				return true;
			}
		}
	}
}

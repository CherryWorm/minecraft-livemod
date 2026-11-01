package gm.companion.api;

import net.minecraft.client.gui.GuiGraphicsExtractor;

/**
 * A picture a module paints itself and draws on a HUD or a screen, which is how to draw a map, a graph or anything else with too many
 * pixels to fill one at a time. It goes by itself when the module unloads.
 */
public interface ModuleImage {
	int width();

	int height();

	/** Sets one pixel, as 0xAARRGGBB. Nothing shows until {@link #upload}. */
	void setPixel(int x, int y, int color);

	/** Sets every pixel from a list of them, row by row, which is what {@link WorldView#readMap} fills. */
	void setPixels(int[] colors);

	/** Sends the pixels to the graphics card. This takes some time, so do it when they've changed, not every frame. */
	void upload();

	/** Draws it stretched to this size. */
	void draw(GuiGraphicsExtractor graphics, int x, int y, int width, int height);

	/** Draws it stretched to this size and turned around its middle, in degrees clockwise, for a map that turns with the player. */
	void drawTurned(GuiGraphicsExtractor graphics, int x, int y, int width, int height, float degrees);
}

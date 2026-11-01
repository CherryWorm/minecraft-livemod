package gm.companion;

import com.mojang.blaze3d.platform.NativeImage;
import gm.companion.api.ModuleImage;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.resources.Identifier;

/** A module's own picture, on a texture of the game's that the module never sees. */
final class PaintedImage implements ModuleImage {
	private final Identifier id;
	private final DynamicTexture texture;
	private final int width;
	private final int height;

	PaintedImage(String moduleId, int number, int width, int height) {
		this.id = Identifier.fromNamespaceAndPath("gm", "painted/" + moduleId + "_" + number);
		this.width = width;
		this.height = height;
		this.texture = new DynamicTexture(this.id::toString, width, height, true);
		Minecraft.getInstance().getTextureManager().register(this.id, this.texture);
	}

	void close() {
		Minecraft.getInstance().getTextureManager().release(this.id);
	}

	@Override
	public int width() {
		return this.width;
	}

	@Override
	public int height() {
		return this.height;
	}

	@Override
	public void setPixel(int x, int y, int color) {
		if (x >= 0 && y >= 0 && x < this.width && y < this.height) {
			this.texture.getPixels().setPixel(x, y, color);
		}
	}

	@Override
	public void setPixels(int[] colors) {
		if (colors.length < this.width * this.height) {
			throw new IllegalArgumentException("An image of " + this.width + " by " + this.height + " needs " + this.width * this.height + " colours, not " + colors.length);
		}
		NativeImage pixels = this.texture.getPixels();
		for (int y = 0; y < this.height; y++) {
			for (int x = 0; x < this.width; x++) {
				pixels.setPixel(x, y, colors[y * this.width + x]);
			}
		}
	}

	@Override
	public void upload() {
		this.texture.upload();
	}

	@Override
	public void draw(GuiGraphicsExtractor graphics, int x, int y, int width, int height) {
		graphics.blit(RenderPipelines.GUI_TEXTURED, this.id, x, y, 0, 0, width, height, width, height);
	}

	@Override
	public void drawTurned(GuiGraphicsExtractor graphics, int x, int y, int width, int height, float degrees) {
		graphics.pose().pushMatrix();
		graphics.pose().translate(x + width / 2.0F, y + height / 2.0F);
		graphics.pose().rotate((float) Math.toRadians(degrees));
		graphics.blit(RenderPipelines.GUI_TEXTURED, this.id, -width / 2, -height / 2, 0, 0, width, height, width, height);
		graphics.pose().popMatrix();
	}
}

package gm.companion.api;

/**
 * Draws in the world for one frame, at world positions. Nothing is kept, so draw everything again each frame, and nothing here can reach
 * the game's own rendering. What's drawn is see-through or glowing, so to make something solid and lasting use a block.
 */
public interface WorldCanvas {
	double cameraX();

	double cameraY();

	double cameraZ();

	/** A box between two corners, with the whole image on each face. */
	void box(WorldLook look, double x1, double y1, double z1, double x2, double y2, double z2);

	/** Only the edges of a box, as lines this wide in blocks, which is what a selection or a planned area wants. */
	void edges(WorldLook look, double x1, double y1, double z1, double x2, double y2, double z2, float width);

	/** A flat surface at any angle, from one corner along two edges, seen from both sides. */
	void sheet(WorldLook look, double x, double y, double z, double edgeX1, double edgeY1, double edgeZ1, double edgeX2, double edgeY2, double edgeZ2);

	/** A line between two points that always turns its face to the camera, this wide in blocks. The image runs along it. */
	void beam(WorldLook look, double x1, double y1, double z1, double x2, double y2, double z2, float width);

	/** A picture centred on a point that always faces the camera, this big in blocks. */
	void billboard(WorldLook look, double x, double y, double z, float width, float height);

	/** A see-through copy of a vanilla block, by name, like "minecraft:stone". The look's color tints it, and an image or a shader on it is ignored. */
	void block(WorldLook look, int x, int y, int z, String block);

	/** The same for any block, by the number the server gave for it with context.clientBlockId(state), which is the only way to name one of this world's. */
	void block(WorldLook look, int x, int y, int z, int clientBlockId);
}

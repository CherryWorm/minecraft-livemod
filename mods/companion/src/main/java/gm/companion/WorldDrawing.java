package gm.companion;

import com.mojang.blaze3d.pipeline.RenderTarget;
import com.mojang.blaze3d.systems.RenderSystem;
import com.mojang.blaze3d.vertex.DefaultVertexFormat;
import com.mojang.blaze3d.vertex.VertexConsumer;
import com.mojang.renderpearl.api.buffers.GpuBufferSlice;
import com.mojang.renderpearl.api.commands.RenderPass;
import com.mojang.renderpearl.api.pipeline.BindGroupLayout;
import com.mojang.renderpearl.api.pipeline.BlendFunction;
import com.mojang.renderpearl.api.pipeline.ColorTargetState;
import com.mojang.renderpearl.api.pipeline.CompareOp;
import com.mojang.renderpearl.api.pipeline.CompiledRenderPipeline;
import com.mojang.renderpearl.api.pipeline.DepthStencilState;
import com.mojang.renderpearl.api.pipeline.PrimitiveTopology;
import com.mojang.renderpearl.api.pipeline.RenderPipeline;
import com.mojang.renderpearl.api.pipeline.UniformType;
import com.mojang.renderpearl.api.textures.FilterMode;
import com.mojang.renderpearl.api.textures.GpuSampler;
import com.mojang.renderpearl.api.textures.GpuTexture;
import com.mojang.renderpearl.api.textures.GpuTextureView;
import gm.companion.api.WorldCanvas;
import gm.companion.api.WorldLook;
import net.minecraft.client.Minecraft;
import net.minecraft.client.model.geom.builders.UVPair;
import net.minecraft.client.renderer.BindGroupLayouts;
import net.minecraft.client.renderer.StagedVertexBuffer;
import net.minecraft.client.renderer.block.dispatch.BlockStateModelPart;
import net.minecraft.client.renderer.culling.Frustum;
import net.minecraft.client.renderer.state.level.CameraRenderState;
import net.minecraft.client.renderer.texture.AbstractTexture;
import net.minecraft.client.renderer.texture.TextureAtlas;
import net.minecraft.client.resources.model.geometry.BakedQuad;
import net.minecraft.commands.arguments.blocks.BlockStateParser;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
import net.minecraft.util.RandomSource;
import net.minecraft.util.Mth;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import org.joml.Vector3f;
import org.joml.Vector3fc;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalDouble;
import java.util.Set;

/**
 * Everything drawn at a place in the world, whether a client module asked for it this frame or the server asked for it to stay a while.
 * It has a render pass of its own at the end of the world's main pass, because that works the same with either of the game's ways of
 * doing transparency, where the game's own submits would crash the game under one of them without a variant of every shader. The catch is
 * that it's drawn after water and tinted glass, so something behind those doesn't show through them.
 */
public final class WorldDrawing {
	private static final Logger LOGGER = LoggerFactory.getLogger("Companion");
	// Starting values, to be tuned once real players' computers have shown what they can draw. The test client renders in software, so it can't say.
	private static final int MOST_QUADS_A_FRAME = 16384;
	private static final int MOST_SHADERS_A_FRAME = 8;
	private static final int MOST_KEPT_SHAPES = 8192;
	private static final float MOST_SHAKE = 5.0F;
	private static final float MOST_SHAKE_SECONDS = 10.0F;
	private static final int STAGING_BYTES = 256 * 1024;
	private static final int HASH_LENGTH = 16;
	private static final float BLOCK_OVERSIZE = 0.002F;
	private static final long NANOS_A_SECOND = 1_000_000_000L;
	private static final Identifier VERTEX_SHADER = Identifier.fromNamespaceAndPath("companion", "world/shape");
	private static final Identifier PLAIN_SHADER = Identifier.fromNamespaceAndPath("companion", "world/plain");
	private static final Identifier WHITE = Identifier.fromNamespaceAndPath("companion", "textures/world/white.png");
	private static final BindGroupLayout SCENE_LAYOUT = BindGroupLayout.builder().withUniform("SceneSampler", UniformType.COMBINED_IMAGE_SAMPLER).build();
	private static final String SCENE_UNIFORM = "SceneSampler";
	// The four corners of a face, as how far along each of its two edges they are.
	private static final float[][] CORNERS = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
	private static final int BOX = 0;
	private static final int SHEET = 1;
	private static final int BEAM = 2;
	private static final int BILLBOARD = 3;
	private static final int BLOCK = 4;
	static final int BURST = 5;
	private static final int MOST_SPECKS = 512;
	// How far a speck's speed can fall short of the burst's, so that they don't all make one neat ball.
	private static final double SLOWEST_SPECK = 0.4;

	private final List<Item> frame = new ArrayList<>();
	private final Map<String, Kept> kept = new LinkedHashMap<>();
	private final Map<PipelineKey, RenderPipeline> pipelines = new HashMap<>();
	private final Map<Identifier, Boolean> readsScene = new HashMap<>();
	private int burstsMade;
	private final Set<Identifier> failedShaders = new HashSet<>();
	private final Map<Integer, List<BakedQuad>> blockQuads = new HashMap<>();
	private final RandomSource random = RandomSource.create(0);
	private StagedVertexBuffer vertices;
	private GpuTexture sceneCopy;
	private GpuTextureView sceneView;
	private int quadsThisFrame;
	private boolean warnedOfTooMany;
	private boolean broken;
	private float shakeStrength;
	private long shakeStarted;
	private float shakeSeconds;

	/**
	 * One thing to draw. How it's stored depends on its kind: a box has its two corners, a sheet a corner and two edges, a beam its two
	 * ends and a billboard its middle. So its position is always in x1, y1 and z1.
	 */
	public record Shape(int kind, double x1, double y1, double z1, double x2, double y2, double z2, double x3, double y3, double z3,
			float width, float height, int blockId, int color, Identifier image, Identifier shader, boolean glowing, boolean throughWalls) {
		private Batch batch() {
			return new Batch(this.shader, this.glowing, this.throughWalls, this.kind == BLOCK ? TextureAtlas.LOCATION_BLOCKS : this.image);
		}
	}

	private record Batch(Identifier shader, boolean glowing, boolean throughWalls, Identifier image) {}

	private record PipelineKey(Identifier shader, boolean glowing, boolean throughWalls) {}

	/** One shape in this frame's list, moved as far as it's got by now, and faded as far as it's got. */
	private record Item(Shape shape, double moveX, double moveY, double moveZ, float alpha, double distance) {}

	/** What the server asked to have shown, which stays until it runs out or is replaced. Zero seconds means it stays until it's taken away. */
	private record Kept(List<Shape> shapes, long born, float seconds, float fade, float moveX, float moveY, float moveZ) {}

	// What modules and the server ask for ------------------------------------------------------------------------

	WorldCanvas canvas(String moduleId) {
		return new Canvas(moduleId);
	}

	void keep(String moduleId, String key, List<Shape> shapes, float seconds, float age, float fade, float moveX, float moveY, float moveZ) {
		if (shapes.size() > MOST_KEPT_SHAPES) {
			shapes = shapes.subList(0, MOST_KEPT_SHAPES);
		}
		this.kept.put(moduleId + "/" + key, new Kept(shapes, System.nanoTime() - (long) (age * NANOS_A_SECOND), seconds, fade, moveX, moveY, moveZ));
	}

	void takeAway(String moduleId, String key) {
		if (key.isEmpty()) {
			this.kept.keySet().removeIf(name -> name.startsWith(moduleId + "/"));
		} else {
			this.kept.remove(moduleId + "/" + key);
		}
	}

	void forget() {
		this.kept.clear();
		this.shakeStrength = 0;
	}

	/** What's kept is about a place in one dimension, so it doesn't follow a player to another. The server sends it again if they come back. */
	void levelChanged() {
		this.kept.clear();
	}

	void shake(float strength, float seconds) {
		this.shakeStrength = Mth.clamp(strength, 0, MOST_SHAKE);
		this.shakeSeconds = Mth.clamp(seconds, 0, MOST_SHAKE_SECONDS);
		this.shakeStarted = System.nanoTime();
	}

	/** How far to turn the view this frame, in degrees, as a yaw and a pitch. A few sines at unrelated speeds are enough to look like shaking. */
	public void shakeOffset(float[] into) {
		into[0] = 0;
		into[1] = 0;
		if (this.shakeStrength <= 0) {
			return;
		}
		float time = (System.nanoTime() - this.shakeStarted) / (float) NANOS_A_SECOND;
		if (time >= this.shakeSeconds) {
			this.shakeStrength = 0;
			return;
		}
		float scale = this.shakeStrength * (1 - time / this.shakeSeconds) * Minecraft.getInstance().options.screenEffectScale().get().floatValue();
		into[0] = scale * (Mth.sin(time * 37.0F) + 0.5F * Mth.sin(time * 61.0F)) / 1.5F;
		into[1] = scale * (Mth.sin(time * 43.0F + 1.0F) + 0.5F * Mth.sin(time * 71.0F)) / 1.5F;
	}

	/** The name a feature's shader or image has in the resource pack, which the broker works out the same way, so that it gives nothing away. */
	static Identifier packId(String moduleId, String folder, String name, String suffix) {
		if (name == null || name.isEmpty()) {
			return null;
		}
		try {
			String full = name.contains("/") ? name : moduleId + "/" + name;
			byte[] digest = MessageDigest.getInstance("SHA-256").digest(full.getBytes(StandardCharsets.UTF_8));
			return Identifier.fromNamespaceAndPath("gm", folder + "/p" + HexFormat.of().formatHex(digest).substring(0, HASH_LENGTH) + suffix);
		} catch (NoSuchAlgorithmException error) {
			throw new IllegalStateException(error);
		}
	}

	static Identifier imageId(String moduleId, String name) {
		return packId(moduleId, "textures/world", name, ".png");
	}

	static Identifier shaderId(String moduleId, String name) {
		return packId(moduleId, "world", name, "");
	}

	private static Shape shape(int kind, double x1, double y1, double z1, double x2, double y2, double z2, double x3, double y3, double z3, float width, float height, int blockId, WorldLook look, String moduleId) {
		return new Shape(kind, x1, y1, z1, x2, y2, z2, x3, y3, z3, width, height, blockId, look.color(), imageId(moduleId, look.image()), shaderId(moduleId, look.shader()), look.isGlowing(), look.isThroughWalls());
	}

	/** What the server sent, in the same form as what a module draws. */
	static Shape shape(int kind, double[] places, float width, float height, int blockId, int color, Identifier image, Identifier shader, boolean glowing, boolean throughWalls) {
		return new Shape(kind, places[0], places[1], places[2], places[3], places[4], places[5], places[6], places[7], places[8], width, height, blockId, color, image, shader, glowing, throughWalls);
	}

	private final class Canvas implements WorldCanvas {
		private final String moduleId;

		Canvas(String moduleId) {
			this.moduleId = moduleId;
		}

		private Vec3 camera() {
			return Minecraft.getInstance().gameRenderer.gameRenderState().levelRenderState.cameraRenderState.pos;
		}

		@Override
		public double cameraX() {
			return camera().x;
		}

		@Override
		public double cameraY() {
			return camera().y;
		}

		@Override
		public double cameraZ() {
			return camera().z;
		}

		@Override
		public void box(WorldLook look, double x1, double y1, double z1, double x2, double y2, double z2) {
			add(shape(BOX, x1, y1, z1, x2, y2, z2, 0, 0, 0, 0, 0, 0, look, this.moduleId));
		}

		@Override
		public void edges(WorldLook look, double x1, double y1, double z1, double x2, double y2, double z2, float width) {
			for (double y : new double[] {y1, y2}) {
				beam(look, x1, y, z1, x2, y, z1, width);
				beam(look, x1, y, z2, x2, y, z2, width);
				beam(look, x1, y, z1, x1, y, z2, width);
				beam(look, x2, y, z1, x2, y, z2, width);
			}
			for (double[] corner : new double[][] {{x1, z1}, {x1, z2}, {x2, z1}, {x2, z2}}) {
				beam(look, corner[0], y1, corner[1], corner[0], y2, corner[1], width);
			}
		}

		@Override
		public void sheet(WorldLook look, double x, double y, double z, double edgeX1, double edgeY1, double edgeZ1, double edgeX2, double edgeY2, double edgeZ2) {
			add(shape(SHEET, x, y, z, edgeX1, edgeY1, edgeZ1, edgeX2, edgeY2, edgeZ2, 0, 0, 0, look, this.moduleId));
		}

		@Override
		public void beam(WorldLook look, double x1, double y1, double z1, double x2, double y2, double z2, float width) {
			add(shape(BEAM, x1, y1, z1, x2, y2, z2, 0, 0, 0, width, 0, 0, look, this.moduleId));
		}

		@Override
		public void billboard(WorldLook look, double x, double y, double z, float width, float height) {
			add(shape(BILLBOARD, x, y, z, 0, 0, 0, 0, 0, 0, width, height, 0, look, this.moduleId));
		}

		@Override
		public void block(WorldLook look, int x, int y, int z, String block) {
			int id = namedBlockId(block);
			if (id >= 0) {
				block(look, x, y, z, id);
			}
		}

		@Override
		public void block(WorldLook look, int x, int y, int z, int clientBlockId) {
			add(new Shape(BLOCK, x, y, z, 0, 0, 0, 0, 0, 0, 0, 0, clientBlockId, look.color(), null, null, look.isGlowing(), look.isThroughWalls()));
		}

		private void add(Shape shape) {
			addToFrame(shape, 0, 0, 0, 1);
		}
	}

	private static int namedBlockId(String name) {
		try {
			BlockState state = BlockStateParser.parseForBlock(BuiltInRegistries.BLOCK, name, false).blockState();
			return Block.BLOCK_STATE_REGISTRY.getId(state);
		} catch (com.mojang.brigadier.exceptions.CommandSyntaxException error) {
			return -1;
		}
	}

	// Drawing ----------------------------------------------------------------------------------------------------

	private int quadCount(Shape shape) {
		return switch (shape.kind()) {
			case BOX -> 6;
			case BLOCK -> blockQuads(shape.blockId()).size();
			default -> 1;
		};
	}

	private void addToFrame(Shape shape, double moveX, double moveY, double moveZ, float alpha) {
		int quads = quadCount(shape);
		if (this.quadsThisFrame + quads > MOST_QUADS_A_FRAME) {
			if (!this.warnedOfTooMany) {
				this.warnedOfTooMany = true;
				LOGGER.warn("More is being drawn in the world than the limit of {} quads a frame, so the rest doesn't appear", MOST_QUADS_A_FRAME);
			}
			return;
		}
		this.quadsThisFrame += quads;
		this.frame.add(new Item(shape, moveX, moveY, moveZ, alpha, 0));
	}

	private void addKept() {
		long now = System.nanoTime();
		var entries = this.kept.values().iterator();
		while (entries.hasNext()) {
			Kept each = entries.next();
			float age = (now - each.born()) / (float) NANOS_A_SECOND;
			if (each.seconds() > 0 && age >= each.seconds()) {
				entries.remove();
				continue;
			}
			float left = each.seconds() - age;
			float alpha = each.seconds() > 0 && each.fade() > 0 && left < each.fade() ? left / each.fade() : 1;
			for (Shape shape : each.shapes()) {
				if (shape.kind() == BURST) {
					addBurst(shape, age, alpha, each.moveX() * age, each.moveY() * age, each.moveZ() * age);
				} else {
					addToFrame(shape, each.moveX() * age, each.moveY() * age, each.moveZ() * age, alpha);
				}
			}
		}
	}

	/** Where each speck is comes from its number and how old the burst is, so nothing has to be kept for each one, however many there are. */
	private void addBurst(Shape burst, float age, float alpha, double moveX, double moveY, double moveZ) {
		long seed = (long) burst.z2();
		int count = Math.min((int) burst.height(), MOST_SPECKS);
		for (int index = 0; index < count; index++) {
			double angle = Mth.TWO_PI * unit(seed, index, 1);
			double up = 2 * unit(seed, index, 2) - 1;
			double out = Math.sqrt(1 - up * up);
			double distance = burst.x2() * age * (SLOWEST_SPECK + (1 - SLOWEST_SPECK) * unit(seed, index, 3));
			double x = burst.x1() + Math.cos(angle) * out * distance;
			double y = burst.y1() + up * distance - burst.y2() * age * age / 2;
			double z = burst.z1() + Math.sin(angle) * out * distance;
			addToFrame(new Shape(BILLBOARD, x, y, z, 0, 0, 0, 0, 0, 0, burst.width(), burst.width(), 0, burst.color(), burst.image(), burst.shader(), burst.glowing(), burst.throughWalls()), moveX, moveY, moveZ, alpha);
		}
	}

	/** A number from 0 to 1 that's always the same for the same three, and looks random. */
	private static double unit(long seed, int index, int which) {
		long mixed = (seed * 1_000_003L + index) * 1_000_003L + which;
		mixed = (mixed ^ (mixed >>> 33)) * 0xFF51AFD7ED558CCDL;
		mixed = (mixed ^ (mixed >>> 33)) * 0xC4CEB9FE1A85EC53L;
		return ((mixed ^ (mixed >>> 33)) >>> 11) * 0x1.0p-53;
	}

	/** A burst from a client module, which goes by itself when its time is up. */
	void keepBurst(String moduleId, WorldLook look, double x, double y, double z, int count, float speed, float size, float gravity, float seconds) {
		Shape burst = shape(BURST, x, y, z, speed, gravity, ++this.burstsMade, 0, 0, 0, size, count, 0, look, moduleId);
		keep(moduleId, "burst " + this.burstsMade, List.of(burst), seconds, 0, seconds / 2, 0, 0, 0);
	}

	private static AABB bounds(Shape shape, double moveX, double moveY, double moveZ) {
		double x1 = shape.x1() + moveX;
		double y1 = shape.y1() + moveY;
		double z1 = shape.z1() + moveZ;
		return switch (shape.kind()) {
			case BOX, BEAM -> {
				double grow = shape.width();
				yield new AABB(x1, y1, z1, shape.x2() + moveX, shape.y2() + moveY, shape.z2() + moveZ).inflate(grow);
			}
			case SHEET -> new AABB(x1, y1, z1, x1 + shape.x2() + shape.x3(), y1 + shape.y2() + shape.y3(), z1 + shape.z2() + shape.z3())
					.minmax(new AABB(x1 + shape.x2(), y1 + shape.y2(), z1 + shape.z2(), x1 + shape.x3(), y1 + shape.y3(), z1 + shape.z3()));
			case BILLBOARD -> new AABB(x1, y1, z1, x1, y1, z1).inflate(Math.max(shape.width(), shape.height()));
			default -> new AABB(x1, y1, z1, x1 + 1, y1 + 1, z1 + 1);
		};
	}

	private List<Item> visibleFarthestFirst(CameraRenderState camera) {
		Frustum frustum = camera.cullFrustum;
		List<Item> visible = new ArrayList<>(this.frame.size());
		for (Item item : this.frame) {
			AABB box = bounds(item.shape(), item.moveX(), item.moveY(), item.moveZ());
			if (frustum.isVisible(box)) {
				visible.add(new Item(item.shape(), item.moveX(), item.moveY(), item.moveZ(), item.alpha(), box.getCenter().distanceToSqr(camera.pos)));
			}
		}
		visible.sort(Comparator.comparingDouble(Item::distance).reversed());
		return visible;
	}

	/** The world has just finished drawing. Modules draw now, because anything a frame's early passes care about has already been worked out. */
	void render(Runnable modules, RenderTarget target, CameraRenderState camera) {
		if (this.broken) {
			return;
		}
		this.frame.clear();
		this.quadsThisFrame = 0;
		try {
			modules.run();
			addKept();
			if (!this.frame.isEmpty()) {
				draw(target, camera);
			}
		} catch (RuntimeException | LinkageError error) {
			// Whatever went wrong, this isn't worth losing the player's game over.
			this.broken = true;
			LOGGER.error("Stopped drawing in the world, until the game next starts", error);
		}
	}

	private void draw(RenderTarget target, CameraRenderState camera) {
		if (this.vertices == null) {
			this.vertices = new StagedVertexBuffer(() -> "World shapes", STAGING_BYTES);
		}
		List<Item> items = visibleFarthestFirst(camera);
		if (items.isEmpty()) {
			return;
		}
		List<Batch> batches = new ArrayList<>();
		List<StagedVertexBuffer.Draw> draws = new ArrayList<>();
		Set<Identifier> shaders = new HashSet<>();
		Batch last = null;
		VertexConsumer out = null;
		for (Item item : items) {
			Batch batch = item.shape().batch();
			if (batch.shader() != null && (this.failedShaders.contains(batch.shader()) || !shaders.contains(batch.shader()) && shaders.size() >= MOST_SHADERS_A_FRAME)) {
				continue;
			}
			if (batch.shader() != null) {
				shaders.add(batch.shader());
			}
			if (!batch.equals(last)) {
				StagedVertexBuffer.Draw draw = this.vertices.appendDraw(DefaultVertexFormat.POSITION_TEX_COLOR, PrimitiveTopology.QUADS);
				out = this.vertices.getVertexBuilder(draw);
				batches.add(batch);
				draws.add(draw);
				last = batch;
			}
			emit(out, item, camera);
		}
		this.vertices.upload();
		// All of this can wait on the graphics card, which isn't allowed once a render pass is open.
		List<CompiledRenderPipeline> compiled = new ArrayList<>();
		List<AbstractTexture> textures = new ArrayList<>();
		boolean scene = false;
		for (Batch batch : batches) {
			RenderPipeline pipeline = pipelineFor(new PipelineKey(batch.shader(), batch.glowing(), batch.throughWalls()));
			CompiledRenderPipeline ready = pipeline == null ? null : RenderSystem.getCompiledPipelineNullable(pipeline);
			if (ready == null && batch.shader() != null) {
				this.failedShaders.add(batch.shader());
			}
			compiled.add(ready);
			textures.add(Minecraft.getInstance().getTextureManager().getTexture(batch.image() != null ? batch.image() : WHITE));
			scene |= ready != null && batch.shader() != null && readsScene(batch.shader());
		}
		if (scene) {
			copyScene(target);
		}
		GpuBufferSlice transforms = RenderSystem.getDynamicUniforms().writeTransform(RenderSystem.getModelViewMatrixCopy());
		GpuSampler imageSampler = RenderSystem.getSamplerCache().getRepeat(FilterMode.NEAREST);
		try (RenderPass pass = RenderSystem.getDevice().createCommandEncoder().createRenderPass(() -> "World shapes", target.getColorTextureView(), Optional.empty(), target.getDepthTextureView(), OptionalDouble.empty())) {
			RenderSystem.bindDefaultUniforms(pass);
			pass.setUniform("DynamicTransforms", transforms);
			if (scene) {
				pass.setUniform(SCENE_UNIFORM, this.sceneView, RenderSystem.getSamplerCache().getClampToEdge(FilterMode.LINEAR));
			}
			for (int index = 0; index < batches.size(); index++) {
				StagedVertexBuffer.ExecuteInfo info = this.vertices.getExecuteInfo(draws.get(index));
				if (info == null || compiled.get(index) == null) {
					continue;
				}
				Batch batch = batches.get(index);
				pass.setPipeline(compiled.get(index));
				AbstractTexture texture = textures.get(index);
				pass.setUniform("Sampler0", texture.getTextureView(), batch.image() == TextureAtlas.LOCATION_BLOCKS ? texture.getSampler() : imageSampler);
				pass.setVertexBuffer(0, info.vertexBuffer().slice());
				pass.setIndexBuffer(info.indexBuffer(), info.indexType());
				pass.drawIndexed(info.indexCount(), 1, info.firstIndex(), info.baseVertex(), 0);
			}
		}
		this.vertices.endFrame();
	}

	private void emit(VertexConsumer out, Item item, CameraRenderState camera) {
		Shape shape = item.shape();
		float x = (float) (shape.x1() + item.moveX() - camera.pos.x);
		float y = (float) (shape.y1() + item.moveY() - camera.pos.y);
		float z = (float) (shape.z1() + item.moveZ() - camera.pos.z);
		int color = faded(shape.color(), item.alpha());
		switch (shape.kind()) {
			case BOX -> {
				float width = (float) (shape.x2() - shape.x1());
				float height = (float) (shape.y2() - shape.y1());
				float depth = (float) (shape.z2() - shape.z1());
				face(out, x, y, z, width, 0, 0, 0, 0, depth, color);
				face(out, x, y + height, z, width, 0, 0, 0, 0, depth, color);
				face(out, x, y, z, width, 0, 0, 0, height, 0, color);
				face(out, x, y, z + depth, width, 0, 0, 0, height, 0, color);
				face(out, x, y, z, 0, 0, depth, 0, height, 0, color);
				face(out, x + width, y, z, 0, 0, depth, 0, height, 0, color);
			}
			case SHEET -> face(out, x, y, z, (float) shape.x2(), (float) shape.y2(), (float) shape.z2(), (float) shape.x3(), (float) shape.y3(), (float) shape.z3(), color);
			case BEAM -> beam(out, x, y, z, (float) (shape.x2() + item.moveX() - camera.pos.x), (float) (shape.y2() + item.moveY() - camera.pos.y), (float) (shape.z2() + item.moveZ() - camera.pos.z), shape.width(), color);
			case BILLBOARD -> {
				Vector3f right = new Vector3f(shape.width(), 0, 0).rotate(camera.orientation);
				Vector3f up = new Vector3f(0, shape.height(), 0).rotate(camera.orientation);
				face(out, x - right.x / 2 - up.x / 2, y - right.y / 2 - up.y / 2, z - right.z / 2 - up.z / 2, right.x, right.y, right.z, up.x, up.y, up.z, color);
			}
			case BLOCK -> block(out, x, y, z, shape.blockId(), color);
			default -> {}
		}
	}

	private static int faded(int color, float alpha) {
		return alpha >= 1 ? color : color & 0xFFFFFF | Math.round((color >>> 24) * alpha) << 24;
	}

	private static void face(VertexConsumer out, float x, float y, float z, float edgeX1, float edgeY1, float edgeZ1, float edgeX2, float edgeY2, float edgeZ2, int color) {
		for (float[] corner : CORNERS) {
			out.addVertex(x + corner[0] * edgeX1 + corner[1] * edgeX2, y + corner[0] * edgeY1 + corner[1] * edgeY2, z + corner[0] * edgeZ1 + corner[1] * edgeZ2).setUv(corner[0], 1 - corner[1]).setColor(color);
		}
	}

	/** Each end turns to the camera by itself, so a beam reaching far away and passing close by keeps its width. */
	private static void beam(VertexConsumer out, float x1, float y1, float z1, float x2, float y2, float z2, float width, int color) {
		Vector3f along = new Vector3f(x2 - x1, y2 - y1, z2 - z1);
		Vector3f sideAtStart = new Vector3f(x1, y1, z1).cross(along);
		Vector3f sideAtEnd = new Vector3f(x2, y2, z2).cross(along);
		// Looking right along it, there's no side to turn to, and the beam is only a point anyway.
		if (sideAtStart.lengthSquared() < 1.0E-6F || sideAtEnd.lengthSquared() < 1.0E-6F) {
			return;
		}
		sideAtStart.normalize(width / 2);
		sideAtEnd.normalize(width / 2);
		out.addVertex(x1 - sideAtStart.x, y1 - sideAtStart.y, z1 - sideAtStart.z).setUv(0, 0).setColor(color);
		out.addVertex(x1 + sideAtStart.x, y1 + sideAtStart.y, z1 + sideAtStart.z).setUv(1, 0).setColor(color);
		out.addVertex(x2 + sideAtEnd.x, y2 + sideAtEnd.y, z2 + sideAtEnd.z).setUv(1, 1).setColor(color);
		out.addVertex(x2 - sideAtEnd.x, y2 - sideAtEnd.y, z2 - sideAtEnd.z).setUv(0, 1).setColor(color);
	}

	private void block(VertexConsumer out, float x, float y, float z, int blockId, int color) {
		float grow = 1 + BLOCK_OVERSIZE * 2;
		for (BakedQuad quad : blockQuads(blockId)) {
			for (int corner = 0; corner < BakedQuad.VERTEX_COUNT; corner++) {
				Vector3fc place = quad.position(corner);
				long uv = quad.packedUV(corner);
				out.addVertex(x + place.x() * grow - BLOCK_OVERSIZE, y + place.y() * grow - BLOCK_OVERSIZE, z + place.z() * grow - BLOCK_OVERSIZE)
						.setUv(UVPair.unpackU(uv), UVPair.unpackV(uv)).setColor(color);
			}
		}
	}

	private List<BakedQuad> blockQuads(int blockId) {
		return this.blockQuads.computeIfAbsent(blockId, id -> {
			BlockState state = Block.BLOCK_STATE_REGISTRY.byId(id);
			if (state == null) {
				return List.of();
			}
			List<BlockStateModelPart> parts = new ArrayList<>();
			this.random.setSeed(0);
			Minecraft.getInstance().getModelManager().getBlockStateModelSet().get(state).collectParts(this.random, parts);
			List<BakedQuad> quads = new ArrayList<>();
			for (BlockStateModelPart part : parts) {
				for (Direction direction : Direction.values()) {
					quads.addAll(part.getQuads(direction));
				}
				quads.addAll(part.getQuads(null));
			}
			return quads;
		});
	}

	private RenderPipeline pipelineFor(PipelineKey key) {
		return this.pipelines.computeIfAbsent(key, wanted -> {
			Identifier fragment = wanted.shader() != null ? wanted.shader() : PLAIN_SHADER;
			String name = fragment.getNamespace() + "_" + fragment.getPath().replace('/', '_') + (wanted.glowing() ? "_glowing" : "") + (wanted.throughWalls() ? "_through" : "");
			RenderPipeline.Builder builder = RenderPipeline.builder()
					.withLocation(Identifier.fromNamespaceAndPath("companion", "pipeline/world_" + name))
					.withBindGroupLayout(BindGroupLayouts.GLOBALS)
					.withBindGroupLayout(BindGroupLayouts.PROJECTION)
					.withBindGroupLayout(BindGroupLayouts.DYNAMIC_TRANSFORMS)
					.withBindGroupLayout(BindGroupLayouts.FOG)
					.withBindGroupLayout(BindGroupLayouts.SAMPLER0)
					.withVertexShader(VERTEX_SHADER)
					.withFragmentShader(fragment)
					.withVertexBinding(0, DefaultVertexFormat.POSITION_TEX_COLOR)
					.withPrimitiveTopology(PrimitiveTopology.QUADS)
					.withCull(false)
					.withColorTargetState(new ColorTargetState(wanted.glowing() ? BlendFunction.LIGHTNING : BlendFunction.TRANSLUCENT))
					.withDepthStencilState(new DepthStencilState(wanted.throughWalls() ? CompareOp.ALWAYS_PASS : CompareOp.GREATER_THAN_OR_EQUAL, false));
			if (wanted.glowing() && wanted.shader() == null) {
				builder.withShaderDefine("NO_FOG");
			}
			if (wanted.shader() != null && readsScene(wanted.shader())) {
				builder.withBindGroupLayout(SCENE_LAYOUT);
			}
			return builder.build();
		});
	}

	/** Copying the picture so far is cheap but not free, so it only happens for a shader that really looks at it. */
	private boolean readsScene(Identifier shader) {
		return this.readsScene.computeIfAbsent(shader, id -> {
			Identifier file = Identifier.fromNamespaceAndPath(id.getNamespace(), "shaders/" + id.getPath() + ".fsh");
			try (BufferedReader reader = Minecraft.getInstance().getResourceManager().openAsReader(file)) {
				return reader.lines().anyMatch(line -> line.contains(SCENE_UNIFORM));
			} catch (IOException error) {
				return false;
			}
		});
	}

	private void copyScene(RenderTarget target) {
		if (this.sceneCopy == null || this.sceneCopy.getWidth(0) != target.width || this.sceneCopy.getHeight(0) != target.height) {
			closeSceneCopy();
			this.sceneCopy = RenderSystem.getDevice().createTexture(() -> "World shapes scene copy", GpuTexture.USAGE_COPY_DST | GpuTexture.USAGE_TEXTURE_BINDING, target.getColorTexture().getFormat(), target.width, target.height, 1, 1);
			this.sceneView = RenderSystem.getDevice().createTextureView(this.sceneCopy);
		}
		RenderSystem.getDevice().createCommandEncoder().copyTextureToTexture(target.getColorTexture(), this.sceneCopy, 0, 0, 0, 0, 0, target.width, target.height);
	}

	private void closeSceneCopy() {
		if (this.sceneView != null) {
			this.sceneView.close();
			this.sceneView = null;
		}
		if (this.sceneCopy != null) {
			this.sceneCopy.close();
			this.sceneCopy = null;
		}
	}

	/** Shaders and models go when resource packs change, and the pack may now have a shader that wasn't there before. */
	public void resourcesReloaded() {
		this.pipelines.clear();
		this.readsScene.clear();
		this.failedShaders.clear();
		this.blockQuads.clear();
	}

	/** Whether one of this world's shaders compiles here. It's what the release gate asks of a real client. */
	public boolean compiles(Identifier shader) {
		RenderPipeline pipeline = pipelineFor(new PipelineKey(shader, false, false));
		return RenderSystem.getCompiledPipelineNullable(pipeline) != null;
	}
}

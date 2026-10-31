package gm.conduit.slots;

import eu.pb4.polymer.blocks.api.BlockModelType;
import net.minecraft.world.level.block.SoundType;
import net.minecraft.world.level.block.state.BlockBehaviour;

import java.util.function.Supplier;

/**
 * The kinds of blank block registered at boot. Properties like hardness and light can't change on a
 * live block, so each combination the agent might want has its own family.
 *
 * <p>Each family owns a fixed ID range, so its IDs can never shift between releases. Counts may grow
 * up to the range size but must never shrink, because worlds store these IDs. Together the counts stay
 * below Polymer's limit for each model type, leaving room in reserve.
 */
public enum SlotFamily {
	STONE(1000, 150, BlockModelType.FULL_BLOCK, () -> base(1.5f, 6.0f, SoundType.STONE).requiresCorrectToolForDrops()),
	ORE(1200, 120, BlockModelType.FULL_BLOCK, () -> base(3.0f, 3.0f, SoundType.STONE).requiresCorrectToolForDrops()),
	DEEP_ORE(1400, 60, BlockModelType.FULL_BLOCK, () -> base(4.5f, 3.0f, SoundType.DEEPSLATE).requiresCorrectToolForDrops()),
	METAL(1500, 50, BlockModelType.FULL_BLOCK, () -> base(5.0f, 6.0f, SoundType.METAL).requiresCorrectToolForDrops()),
	WOOD(1600, 60, BlockModelType.FULL_BLOCK, () -> base(2.0f, 3.0f, SoundType.WOOD)),
	SOIL(1700, 40, BlockModelType.FULL_BLOCK, () -> base(0.6f, 0.6f, SoundType.GRAVEL)),
	GLOW(1800, 40, BlockModelType.FULL_BLOCK, () -> base(1.5f, 3.0f, SoundType.GLASS).lightLevel(state -> 12)),
	MACHINE(1900, 80, BlockModelType.FULL_BLOCK, () -> base(3.5f, 6.0f, SoundType.METAL).requiresCorrectToolForDrops()),
	CUTOUT(2000, 40, BlockModelType.LEAVES, () -> base(0.3f, 0.3f, SoundType.GRASS).noOcclusion()),
	PLANT(2100, 5, BlockModelType.PLANT, () -> base(0.0f, 0.0f, SoundType.GRASS).noCollision().randomTicks()),
	GLOW_PLANT(2110, 2, BlockModelType.PLANT, () -> base(0.0f, 0.0f, SoundType.GRASS).noCollision().randomTicks().lightLevel(state -> 10)),
	TINTED_PLANT(2150, 12, BlockModelType.BIOME_PLANT, () -> base(0.0f, 0.0f, SoundType.GRASS).noCollision().randomTicks());

	private final int firstId;
	private final int count;
	private final BlockModelType modelType;
	private final Supplier<BlockBehaviour.Properties> properties;

	SlotFamily(int firstId, int count, BlockModelType modelType, Supplier<BlockBehaviour.Properties> properties) {
		this.firstId = firstId;
		this.count = count;
		this.modelType = modelType;
		this.properties = properties;
	}

	private static BlockBehaviour.Properties base(float hardness, float resistance, SoundType sound) {
		return BlockBehaviour.Properties.of().strength(hardness, resistance).sound(sound);
	}

	public int firstId() {
		return this.firstId;
	}

	public int count() {
		return this.count;
	}

	public BlockModelType modelType() {
		return this.modelType;
	}

	public BlockBehaviour.Properties properties() {
		return this.properties.get();
	}
}

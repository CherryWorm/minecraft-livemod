package gm.conduit.slots;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.LevelReader;
import net.minecraft.world.level.ScheduledTickAccess;
import net.minecraft.world.level.block.BonemealSource;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.BonemealableBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;
import net.minecraft.world.level.block.state.properties.IntegerProperty;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.VoxelShape;
import org.jspecify.annotations.Nullable;

import java.util.ArrayList;
import java.util.List;

/**
 * A crop with all its growth stages in one slot. It grows by itself, can be bone mealed, keeps its farmland wet and goes if what's
 * under it does. Each stage is a client block state of its own, of which there aren't many, so there are few of these.
 */
public final class CropSlotBlock extends SlotBlock implements BonemealableBlock {
	public static final IntegerProperty AGE = BlockStateProperties.AGE_3;
	public static final int LAST_STAGE = 3;
	private static final int ENOUGH_LIGHT = 9;
	/** What a client takes this for has this outline, and it's easier to aim at than something flat. */
	private static final VoxelShape OUTLINE = Block.box(0, 0, 0, 16, 8, 16);

	private final List<BlockState> stages = new ArrayList<>();

	public CropSlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties, family, model, slotId);
		registerDefaultState(defaultBlockState().setValue(AGE, 0));
		for (int stage = 0; stage <= LAST_STAGE; stage++) {
			BlockState state = PolymerBlockResourceUtils.requestBlock(BlockModelType.TRIPWIRE,
					PolymerBlockModel.of(Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "block/" + stageModel(slotId, stage))));
			if (state == null) {
				throw new IllegalStateException("No free tripwire states for " + slotId);
			}
			this.stages.add(state);
		}
	}

	public static String stageModel(String slotId, int stage) {
		return slotId + "_" + stage;
	}

	@Override
	protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {
		super.createBlockStateDefinition(builder);
		builder.add(AGE);
	}

	@Override
	public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
		return this.stages.get(state.getValue(AGE));
	}

	@Override
	protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {
		return OUTLINE;
	}

	@Override
	protected boolean canSurvive(BlockState state, LevelReader level, BlockPos pos) {
		BlockState ground = level.getBlockState(pos.below());
		var on = BlockSettings.of(slotId()).on();
		return on.isEmpty() ? ground.is(Blocks.FARMLAND) : on.contains(ground.getBlock());
	}

	@Override
	protected BlockState updateShape(BlockState state, LevelReader level, ScheduledTickAccess ticks, BlockPos pos, Direction direction, BlockPos neighbourPos, BlockState neighbour, RandomSource random) {
		return direction == Direction.DOWN && !canSurvive(state, level, pos)
				? Blocks.AIR.defaultBlockState()
				: super.updateShape(state, level, ticks, pos, direction, neighbourPos, neighbour, random);
	}

	@Override
	protected void randomTick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {
		if (state.getValue(AGE) < LAST_STAGE && level.getRawBrightness(pos, 0) >= ENOUGH_LIGHT && random.nextFloat() < BlockSettings.of(slotId()).growth()) {
			level.setBlock(pos, state.setValue(AGE, state.getValue(AGE) + 1), Block.UPDATE_CLIENTS);
		}
		super.randomTick(state, level, pos, random);
	}

	@Override
	public boolean isValidBonemealTarget(LevelReader level, BlockPos pos, BlockState state, BonemealSource source) {
		return state.getValue(AGE) < LAST_STAGE;
	}

	@Override
	public boolean isBonemealSuccess(Level level, RandomSource random, BlockPos pos, BlockState state, BonemealSource source) {
		return true;
	}

	@Override
	public void performBonemeal(ServerLevel level, RandomSource random, BlockPos pos, BlockState state, BonemealSource source) {
		level.setBlock(pos, state.setValue(AGE, state.getValue(AGE) + 1), Block.UPDATE_CLIENTS);
	}
}

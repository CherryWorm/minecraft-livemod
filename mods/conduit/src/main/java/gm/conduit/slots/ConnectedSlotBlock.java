package gm.conduit.slots;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.resources.Identifier;
import net.minecraft.util.RandomSource;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.LevelReader;
import net.minecraft.world.level.ScheduledTickAccess;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.PipeBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.VoxelShape;
import org.jspecify.annotations.Nullable;

import java.util.ArrayList;
import java.util.List;

/**
 * A thin line that grows an arm toward each neighbour of its kind, each machine, and whatever else it's told to, like a cable.
 * It's no entity, so it can be placed by the hundred. Each of its 64 shapes is a client block state of its own, of which there
 * aren't many, so there are very few of these. A client takes it for something half a block high, so that's how solid it is.
 */
public final class ConnectedSlotBlock extends SlotBlock {
	private static final Direction[] DIRECTIONS = Direction.values();
	private static final int SHAPES = 1 << DIRECTIONS.length;
	private static final VoxelShape OUTLINE = Block.box(0, 0, 0, 16, 8, 16);

	private final List<BlockState> shapes = new ArrayList<>();

	public ConnectedSlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties, family, model, slotId);
		BlockState resting = defaultBlockState();
		for (Direction direction : DIRECTIONS) {
			resting = resting.setValue(PipeBlock.PROPERTY_BY_DIRECTION.get(direction), false);
		}
		registerDefaultState(resting);
		for (int shape = 0; shape < SHAPES; shape++) {
			BlockState state = PolymerBlockResourceUtils.requestBlock(BlockModelType.SCULK_SENSOR,
					PolymerBlockModel.of(Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "block/" + shapeModel(slotId, shape))));
			if (state == null) {
				throw new IllegalStateException("No free sculk sensor states for " + slotId);
			}
			this.shapes.add(state);
		}
	}

	public static int shapeCount() {
		return SHAPES;
	}

	public static String shapeModel(String slotId, int shape) {
		return slotId + "_c" + shape;
	}

	@Override
	protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {
		super.createBlockStateDefinition(builder);
		for (Direction direction : DIRECTIONS) {
			builder.add(PipeBlock.PROPERTY_BY_DIRECTION.get(direction));
		}
	}

	@Override
	public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
		int shape = 0;
		for (int bit = 0; bit < DIRECTIONS.length; bit++) {
			if (state.getValue(PipeBlock.PROPERTY_BY_DIRECTION.get(DIRECTIONS[bit]))) {
				shape |= 1 << bit;
			}
		}
		return this.shapes.get(shape);
	}

	@Override
	protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {
		return OUTLINE;
	}

	private boolean reachesFor(BlockState other) {
		return other.is(this) || other.getBlock() instanceof MachineSlotBlock || BlockSettings.of(slotId()).connects().contains(other.getBlock());
	}

	@Override
	public @Nullable BlockState getStateForPlacement(BlockPlaceContext context) {
		if (!canPlace(context)) {
			return null;
		}
		BlockState state = defaultBlockState();
		for (Direction direction : DIRECTIONS) {
			BlockState neighbour = context.getLevel().getBlockState(context.getClickedPos().relative(direction));
			state = state.setValue(PipeBlock.PROPERTY_BY_DIRECTION.get(direction), reachesFor(neighbour));
		}
		return state;
	}

	@Override
	protected BlockState updateShape(BlockState state, LevelReader level, ScheduledTickAccess ticks, BlockPos pos, Direction direction, BlockPos neighbourPos, BlockState neighbour, RandomSource random) {
		return state.setValue(PipeBlock.PROPERTY_BY_DIRECTION.get(direction), reachesFor(neighbour));
	}
}

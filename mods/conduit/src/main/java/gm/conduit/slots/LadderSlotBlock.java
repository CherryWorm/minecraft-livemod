package gm.conduit.slots;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
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
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.HorizontalDirectionalBlock;
import net.minecraft.world.level.block.LadderBlock;
import net.minecraft.world.level.block.Mirror;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.EnumProperty;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.VoxelShape;
import org.jspecify.annotations.Nullable;

import java.util.EnumMap;
import java.util.Map;

/**
 * Something to climb. A client works out climbing for itself, from what it takes a block to be, and it has never heard of this world's
 * blocks. So this has to be one of vanilla's climbable blocks to a client, and vines are the ones the pack is free to draw as anything.
 * Each way it can face is a client block state of its own, and it goes on a wall the way a ladder does.
 */
public final class LadderSlotBlock extends SlotBlock {
	public static final EnumProperty<Direction> FACING = HorizontalDirectionalBlock.FACING;
	private static final int QUARTER_TURN = 90;
	private static final int TURNS = 4;

	private final Map<Direction, BlockState> standIns = new EnumMap<>(Direction.class);

	public LadderSlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties, family, model, slotId);
		registerDefaultState(defaultBlockState().setValue(FACING, Direction.NORTH));
		for (Direction facing : Direction.Plane.HORIZONTAL) {
			BlockState state = PolymerBlockResourceUtils.requestBlock(BlockModelType.VINES, PolymerBlockModel.of(model, 0, turnsFromNorth(facing) * QUARTER_TURN));
			if (state == null) {
				throw new IllegalStateException("No free vines states for " + slotId);
			}
			this.standIns.put(facing, state);
		}
	}

	/** The game numbers directions starting from south, and a model starts from north. */
	private static int turnsFromNorth(Direction facing) {
		return (facing.get2DDataValue() + TURNS / 2) % TURNS;
	}

	@Override
	protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {
		super.createBlockStateDefinition(builder);
		builder.add(FACING);
	}

	@Override
	public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
		return this.standIns.get(state.getValue(FACING));
	}

	@Override
	protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {
		return LadderBlock.SHAPES.get(state.getValue(FACING));
	}

	@Override
	protected boolean canSurvive(BlockState state, LevelReader level, BlockPos pos) {
		Direction facing = state.getValue(FACING);
		BlockPos wall = pos.relative(facing.getOpposite());
		return level.getBlockState(wall).isFaceSturdy(level, wall, facing);
	}

	@Override
	protected BlockState updateShape(BlockState state, LevelReader level, ScheduledTickAccess ticks, BlockPos pos, Direction direction, BlockPos neighbourPos, BlockState neighbour, RandomSource random) {
		return direction.getOpposite() == state.getValue(FACING) && !canSurvive(state, level, pos)
				? Blocks.AIR.defaultBlockState()
				: super.updateShape(state, level, ticks, pos, direction, neighbourPos, neighbour, random);
	}

	/** Goes on the wall that was clicked, or whichever is nearest if something else was, as vanilla's ladder does. */
	@Override
	public @Nullable BlockState getStateForPlacement(BlockPlaceContext context) {
		for (Direction direction : context.getNearestLookingDirections()) {
			if (direction.getAxis().isHorizontal()) {
				BlockState state = defaultBlockState().setValue(FACING, direction.getOpposite());
				if (state.canSurvive(context.getLevel(), context.getClickedPos())) {
					return state;
				}
			}
		}
		return null;
	}

	@Override
	protected BlockState rotate(BlockState state, Rotation rotation) {
		return state.setValue(FACING, rotation.rotate(state.getValue(FACING)));
	}

	@Override
	protected BlockState mirror(BlockState state, Mirror mirror) {
		return state.rotate(mirror.getRotation(state.getValue(FACING)));
	}
}

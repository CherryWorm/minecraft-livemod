package gm.conduit.slots;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
import eu.pb4.polymer.blocks.api.PolymerTexturedBlock;
import gm.conduit.api.BlockBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.InsideBlockEffectApplier;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Mirror;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;
import net.minecraft.world.level.block.state.properties.EnumProperty;
import net.minecraft.world.level.block.state.properties.IntegerProperty;
import net.minecraft.world.level.redstone.Orientation;
import net.minecraft.world.phys.BlockHitResult;
import org.jspecify.annotations.Nullable;

import java.util.EnumMap;
import java.util.Map;

/** A blank block. Its behaviour comes from whichever module has bound this slot, if any. */
public class SlotBlock extends Block implements PolymerTexturedBlock {
	/** The game works out a block's light once for each block state, so light that can change has to be part of the state. */
	public static final IntegerProperty LIGHT = IntegerProperty.create("glow", 0, 15);
	public static final EnumProperty<Direction> FACING = BlockStateProperties.FACING;
	/** What bedrock has, which nothing in the game can get through. */
	private static final float BEYOND_ANY_EXPLOSION = 3600000.0F;
	private static final int STRONGEST_SIGNAL = 15;
	private static final int CORRECT_TOOL_DIVISOR = 30;
	private static final int WRONG_TOOL_DIVISOR = 100;
	private static final String HORIZONTAL = "horizontal";
	private static final String ALL = "all";
	private static final int QUARTER = 90;
	private static BlockState emptyState;

	private final BlockState polymerState;
	private final Map<Direction, BlockState> facingStates;
	private final String slotId;
	private final SlotFamily family;

	public SlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties);
		this.slotId = slotId;
		this.family = family;
		this.facingStates = family == SlotFamily.FACING || family == SlotFamily.FACING_MACHINE ? requestFacing(family, model, slotId) : null;
		if (this.facingStates != null) {
			this.polymerState = this.facingStates.get(Direction.NORTH);
		} else {
			this.polymerState = family.modelType() == null
					? emptyState()
					: PolymerBlockResourceUtils.requestBlock(family.modelType(), PolymerBlockModel.of(model));
		}
		if (this.polymerState == null) {
			throw new IllegalStateException("No free " + family.modelType() + " slots for " + slotId);
		}
		registerDefaultState(startingState());
	}

	/** One client block state for each way it can face, all the same model turned round, with the side it calls its front to the north. */
	private static Map<Direction, BlockState> requestFacing(SlotFamily family, Identifier model, String slotId) {
		Map<Direction, BlockState> states = new EnumMap<>(Direction.class);
		for (Direction direction : Direction.values()) {
			int up = direction == Direction.UP ? -QUARTER : direction == Direction.DOWN ? QUARTER : 0;
			int round = direction.getAxis().isHorizontal() ? (int) direction.toYRot() + 2 * QUARTER : 0;
			BlockState state = PolymerBlockResourceUtils.requestBlock(family.modelType(), PolymerBlockModel.of(model, Math.floorMod(up, 4 * QUARTER), Math.floorMod(round, 4 * QUARTER)));
			if (state == null) {
				throw new IllegalStateException("No free " + family.modelType() + " slots for " + slotId);
			}
			states.put(direction, state);
		}
		return states;
	}

	/**
	 * What a client sees for a block drawn by a model: a solid block with nothing to draw. It's a leaves-like one because those
	 * don't hide their neighbours' faces, and all model blocks can share it, since they all look the same to a client.
	 */
	private static BlockState emptyState() {
		if (emptyState == null) {
			emptyState = PolymerBlockResourceUtils.requestEmpty(BlockModelType.LEAVES);
		}
		return emptyState;
	}

	public String slotId() {
		return this.slotId;
	}

	/** Whether this one has a direction it faces. It's asked while the block is being built, so it can't depend on anything of its own. */
	protected boolean turns() {
		return false;
	}

	public boolean isUnbreakable() {
		return BlockSettings.of(this.slotId).unbreakable();
	}

	private BlockState startingState() {
		Integer light = BlockSettings.of(this.slotId).light();
		return defaultBlockState().setValue(LIGHT, light == null ? this.family.startingLight() : light);
	}

	/** A release can change how much light a new one gives. Those already placed keep their own, because it's part of what's in the world. */
	void settingsChanged() {
		registerDefaultState(startingState());
	}

	@Override
	protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {
		builder.add(LIGHT);
		if (turns()) {
			builder.add(FACING);
		}
	}

	@Override
	public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
		return this.facingStates == null ? this.polymerState : this.facingStates.get(state.getValue(FACING));
	}

	/** Null means it can't go there, and the game's own placing takes that as a no, however it got there. */
	@Override
	public @Nullable BlockState getStateForPlacement(BlockPlaceContext context) {
		return canPlace(context) ? turned(defaultBlockState(), context) : null;
	}

	protected final boolean canPlace(BlockPlaceContext context) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		return behavior == null || context.getLevel().isClientSide()
				|| ServerModuleHost.instance().guarded(this.slotId, true, () -> behavior.canPlace(context));
	}

	private BlockState turned(BlockState state, BlockPlaceContext context) {
		if (!turns()) {
			return state;
		}
		String facing = BlockSettings.of(this.slotId).facing();
		if (ALL.equals(facing)) {
			return state.setValue(FACING, context.getNearestLookingDirection().getOpposite());
		}
		return HORIZONTAL.equals(facing) ? state.setValue(FACING, context.getHorizontalDirection().getOpposite()) : state;
	}

	@Override
	public void setPlacedBy(Level level, BlockPos pos, BlockState state, @Nullable LivingEntity by, ItemStack stack) {
		super.setPlacedBy(level, pos, state, by, stack);
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null && !level.isClientSide()) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.placed(state, level, pos, by, stack));
		}
	}

	@Override
	protected BlockState rotate(BlockState state, Rotation rotation) {
		return turns() ? state.setValue(FACING, rotation.rotate(state.getValue(FACING))) : state;
	}

	@Override
	protected BlockState mirror(BlockState state, Mirror mirror) {
		return turns() ? state.setValue(FACING, mirror.mirror(state.getValue(FACING))) : state;
	}

	@Override
	protected InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior == null || level.isClientSide()) {
			return super.useWithoutItem(state, level, pos, player, hit);
		}
		return ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS,
				() -> behavior.use(state, level, pos, player, hit));
	}

	/** A family's hardness is fixed for good, so one that says otherwise is worked out here, the same way the game does it. */
	@Override
	protected float getDestroyProgress(BlockState state, Player player, BlockGetter level, BlockPos pos) {
		BlockSettings settings = BlockSettings.of(this.slotId);
		if (settings.unbreakable()) {
			return 0.0F;
		}
		Float hardness = settings.hardness();
		if (hardness == null) {
			return super.getDestroyProgress(state, player, level, pos);
		}
		return hardness <= 0 ? 1.0F : player.getDestroySpeed(state) / hardness / (player.hasCorrectToolForDrops(state) ? CORRECT_TOOL_DIVISOR : WRONG_TOOL_DIVISOR);
	}

	@Override
	public float getExplosionResistance() {
		return isUnbreakable() ? BEYOND_ANY_EXPLOSION : super.getExplosionResistance();
	}

	@Override
	public void stepOn(Level level, BlockPos pos, BlockState state, Entity entity) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null && !level.isClientSide()) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.stepOn(level, pos, state, entity));
		}
		super.stepOn(level, pos, state, entity);
	}

	/** Called from every block change on a live chunk, because vanilla's own removal hook is skipped by some of them. */
	public void removed(BlockState state, ServerLevel level, BlockPos pos) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.removed(state, level, pos));
		}
	}

	@Override
	protected void randomTick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.randomTick(state, level, pos, random));
		}
	}

	@Override
	protected void tick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.scheduledTick(state, level, pos, random));
		}
	}

	@Override
	protected void neighborChanged(BlockState state, Level level, BlockPos pos, Block neighbor, @Nullable Orientation orientation, boolean movedByPiston) {
		super.neighborChanged(state, level, pos, neighbor, orientation, movedByPiston);
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null && !level.isClientSide()) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.neighborChanged(state, level, pos, neighbor));
		}
	}

	@Override
	protected void entityInside(BlockState state, Level level, BlockPos pos, Entity entity, InsideBlockEffectApplier effects, boolean precise) {
		super.entityInside(state, level, pos, entity, effects, precise);
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null && !level.isClientSide()) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.entityInside(state, level, pos, entity));
		}
	}

	@Override
	protected boolean isSignalSource(BlockState state) {
		return BlockSettings.of(this.slotId).redstone();
	}

	/** The game names the way the asking block looks towards this one. To a builder, it's the side of this block the signal leaves by. */
	@Override
	protected int getSignal(BlockState state, BlockGetter level, BlockPos pos, Direction towards) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior == null || !(level instanceof Level world) || world.isClientSide() || !isSignalSource(state)) {
			return 0;
		}
		return signal(ServerModuleHost.instance().guarded(this.slotId, 0, () -> behavior.redstone(state, world, pos, towards.getOpposite())));
	}

	@Override
	protected int getDirectSignal(BlockState state, BlockGetter level, BlockPos pos, Direction towards) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior == null || !(level instanceof Level world) || world.isClientSide() || !isSignalSource(state)) {
			return 0;
		}
		return signal(ServerModuleHost.instance().guarded(this.slotId, 0, () -> behavior.strongRedstone(state, world, pos, towards.getOpposite())));
	}

	private static int signal(int wanted) {
		return Math.clamp(wanted, 0, STRONGEST_SIGNAL);
	}

	@Override
	protected boolean hasAnalogOutputSignal(BlockState state) {
		return BlockSettings.of(this.slotId).comparator();
	}

	@Override
	protected int getAnalogOutputSignal(BlockState state, Level level, BlockPos pos, Direction direction) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		int said = behavior == null || level.isClientSide() ? BlockBehavior.READ_THE_INVENTORY
				: ServerModuleHost.instance().guarded(this.slotId, BlockBehavior.READ_THE_INVENTORY, () -> behavior.comparator(state, level, pos));
		return said == BlockBehavior.READ_THE_INVENTORY ? AbstractContainerMenu.getRedstoneSignalFromBlockEntity(level.getBlockEntity(pos)) : signal(said);
	}
}

package gm.conduit.api;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

/** What a slot block does. Runs on the server only. A method left out does nothing. */
public interface BlockBehavior {
	/** What {@link #comparator} says to have a comparator read a machine's inventory, the way it reads a chest's. */
	int READ_THE_INVENTORY = -1;

	default InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
		return InteractionResult.PASS;
	}

	default void stepOn(Level level, BlockPos pos, BlockState state, Entity entity) {}

	/** Only the plant families tick randomly. */
	default void randomTick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {}

	/**
	 * This block has left the world, however it went: broken, blown up, pushed by a piston, replaced by a command or by a
	 * module. It's already gone, so state is what it was. A chunk unloading doesn't count, and neither does anything that
	 * happens while this module isn't loaded, so don't rely on this alone for what must stay exactly right. A machine's
	 * data is gone by now too, so see {@link MachineBehavior#removed} for that.
	 */
	default void removed(BlockState state, ServerLevel level, BlockPos pos) {}

	/**
	 * Whether this can go here, asked just before someone places it. Saying no leaves it in their hand. The context has who's placing it, the item,
	 * and where, as {@code context.getClickedPos()}. A dispenser or a module placing one with {@code setBlock} doesn't ask.
	 */
	default boolean canPlace(BlockPlaceContext context) {
		return true;
	}

	/** Someone has just placed this, with this item. {@code by} is null if nobody did, such as a dispenser. A world being made or a module placing one doesn't count. */
	default void placed(BlockState state, Level level, BlockPos pos, LivingEntity by, ItemStack stack) {}

	/**
	 * Whether a player can break this now, asked at the end, when the block would go. Saying no leaves it there, and the player's held back only that far: the cracks
	 * still spread while they dig. To stop digging altogether, use {@code "unbreakable"} in its feature. Explosions, pistons and modules don't ask.
	 */
	default boolean canBreak(BlockState state, Level level, BlockPos pos, Player player) {
		return true;
	}

	/** A delay it asked for has run out, from {@code level.scheduleTick(pos, state.getBlock(), ticks)}. It's how a block does anything later. */
	default void scheduledTick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {}

	/** Something next to it has changed, which is when redstone power reaching it may have changed too: {@code level.getBestNeighborSignal(pos)} says how strong that is. */
	default void neighborChanged(BlockState state, Level level, BlockPos pos, Block neighbor) {}

	/**
	 * The redstone signal it gives out of this side, from 0 to 15, for a block with {@code "redstone": true} in its feature. Keep this quick and don't change anything from
	 * here, because the game asks often. When what this would say changes, call {@code context.redstoneChanged(level, pos)} so its neighbours ask again.
	 */
	default int redstone(BlockState state, Level level, BlockPos pos, Direction side) {
		return 0;
	}

	/** The same, but strong enough to reach through the block it runs into, as a redstone torch does upwards. Most blocks don't need this. */
	default int strongRedstone(BlockState state, Level level, BlockPos pos, Direction side) {
		return 0;
	}

	/** What a comparator reads from it, from 0 to 15, for a block with {@code "comparator": true} in its feature. */
	default int comparator(BlockState state, Level level, BlockPos pos) {
		return READ_THE_INVENTORY;
	}
}

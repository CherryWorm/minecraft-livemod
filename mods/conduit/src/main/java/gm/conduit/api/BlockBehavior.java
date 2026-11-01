package gm.conduit.api;

import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

/** What a slot block does. Runs on the server only. A method left out does nothing. */
public interface BlockBehavior {
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
}

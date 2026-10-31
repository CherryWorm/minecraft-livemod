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
}

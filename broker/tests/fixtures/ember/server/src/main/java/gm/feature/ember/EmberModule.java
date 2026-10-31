package gm.feature.ember;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

/** Test fixture: makes a block respond to being used, to prove modules load and swap live. */
public final class EmberModule implements ServerModule {
	@Override
	public void enable(ServerModuleContext context) {
		context.bindBlock("ember_block", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				player.sendSystemMessage(Component.literal("The block is warm."));
				return InteractionResult.SUCCESS;
			}
		});
	}
}

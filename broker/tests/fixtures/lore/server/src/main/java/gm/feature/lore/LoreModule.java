package gm.feature.lore;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.MachineAttempt;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

import java.util.List;

/** Test fixture: a machine that tries whatever you're holding in both hands, and reacts to near misses. */
public final class LoreModule implements ServerModule {
	@Override
	public void enable(ServerModuleContext context) {
		context.bindBlock("rune_crucible", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				MachineAttempt attempt = context.attemptRecipe(player, "crucible", List.of(player.getMainHandItem(), player.getOffhandItem()));
				if (attempt.succeeded()) {
					player.getMainHandItem().shrink(1);
					player.getOffhandItem().shrink(1);
					player.getInventory().add(attempt.output());
					player.sendSystemMessage(Component.literal("The crucible made something."));
				} else if (attempt.nearMiss()) {
					player.sendSystemMessage(Component.literal("The crucible hums: " + attempt.closest() + " of " + attempt.needed()));
				} else {
					player.sendSystemMessage(Component.literal("The crucible is silent."));
				}
				return InteractionResult.SUCCESS;
			}
		});
	}
}

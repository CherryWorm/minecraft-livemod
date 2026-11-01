package gm.conduit.mixin;

import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.state.BlockState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
import com.llamalad7.mixinextras.sugar.Share;
import com.llamalad7.mixinextras.sugar.ref.LocalRef;

/** Every block a player places by hand comes through here. The stack is copied first, because placing the last one leaves it empty. */
@Mixin(BlockItem.class)
abstract class BlockItemMixin {
	@Inject(method = "place", at = @At("HEAD"))
	private void conduit$rememberStack(BlockPlaceContext context, CallbackInfoReturnable<InteractionResult> info, @Share("stack") LocalRef<ItemStack> stack) {
		stack.set(context.getItemInHand().copy());
	}

	@Inject(method = "place", at = @At("RETURN"))
	private void conduit$tellModules(BlockPlaceContext context, CallbackInfoReturnable<InteractionResult> info, @Share("stack") LocalRef<ItemStack> stack) {
		if (info.getReturnValue() instanceof InteractionResult.Success && context.getPlayer() instanceof ServerPlayer player && context.getLevel() instanceof ServerLevel level) {
			BlockPos pos = context.getClickedPos();
			BlockState state = level.getBlockState(pos);
			ServerModuleHost.instance().fire(events -> events.blockPlaced(player, level, pos, state, stack.get()));
		}
	}
}

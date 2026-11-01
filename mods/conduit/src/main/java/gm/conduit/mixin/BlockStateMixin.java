package gm.conduit.mixin;

import gm.conduit.slots.SlotBlock;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockBehaviour;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** A block's hardness is fixed when it's registered, but this is how the game tells that nothing can break it, pistons included. */
@Mixin(BlockBehaviour.BlockStateBase.class)
abstract class BlockStateMixin {
	private static final float UNBREAKABLE = -1.0F;

	@Shadow
	public abstract Block getBlock();

	@Inject(method = "getDestroySpeed", at = @At("HEAD"), cancellable = true)
	private void conduit$unbreakable(BlockGetter level, BlockPos pos, CallbackInfoReturnable<Float> info) {
		if (getBlock() instanceof SlotBlock block && block.isUnbreakable()) {
			info.setReturnValue(UNBREAKABLE);
		}
	}
}

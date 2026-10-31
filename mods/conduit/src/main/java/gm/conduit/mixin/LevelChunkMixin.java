package gm.conduit.mixin;

import gm.conduit.provenance.Provenance;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(LevelChunk.class)
abstract class LevelChunkMixin {
	@Inject(method = "setBlockState", at = @At("RETURN"))
	private void conduit$recordChange(BlockPos pos, BlockState state, int flags, CallbackInfoReturnable<BlockState> cir) {
		// A null return means the block didn't change.
		if (cir.getReturnValue() != null) {
			Provenance.recordChange((LevelChunk) (Object) this, pos);
		}
	}
}

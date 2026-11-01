package gm.conduit.mixin;

import gm.conduit.provenance.Provenance;
import gm.conduit.slots.SlotBlock;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
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
		BlockState old = cir.getReturnValue();
		if (old != null) {
			LevelChunk chunk = (LevelChunk) (Object) this;
			Provenance.recordChange(chunk, pos);
			if (old.getBlock() instanceof SlotBlock block && !state.is(block) && chunk.getLevel() instanceof ServerLevel level) {
				block.removed(old, level, pos);
			}
		}
	}
}

package gm.feature.clinit_mixin.mixin;

import net.minecraft.world.level.block.Block;
import org.spongepowered.asm.mixin.injection.Desc;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Block.class)
abstract class BoatMixin {
	@Inject(method = "<clinit>", at = @At("HEAD"))
	private static void clinit_mixin$early(CallbackInfo info) {
	}

	@Inject(target = @Desc("<clinit>"), at = @At("TAIL"))
	private static void clinit_mixin$late(CallbackInfo info) {
	}

	@Inject(method = "createBlockStateDefinition", at = @At("HEAD"))
	private void clinit_mixin$states(CallbackInfo info) {
	}
}

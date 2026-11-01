package gm.feature.quiet_mixin.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.LocalCapture;

@Pseudo
@Mixin(AbstractBoat.class)
abstract class BoatMixin {
	@Inject(method = "tick", at = @At("HEAD"), require = 0, locals = LocalCapture.CAPTURE_FAILSOFT)
	private void quiet_mixin$nothing(CallbackInfo info) {
	}
}

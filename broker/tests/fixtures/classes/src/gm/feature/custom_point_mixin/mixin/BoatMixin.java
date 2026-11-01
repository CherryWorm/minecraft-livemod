package gm.feature.custom_point_mixin.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(AbstractBoat.class)
abstract class BoatMixin {
	@Inject(method = "tick", at = @At("gm.feature.custom_point_mixin.shared.Point"))
	private void custom_point_mixin$nothing(CallbackInfo info) {
	}
}

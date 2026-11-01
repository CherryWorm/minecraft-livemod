package gm.feature.patcher_mixin.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixins;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(AbstractBoat.class)
abstract class BoatMixin {
	@Inject(method = "tick", at = @At("HEAD"))
	private void patcher_mixin$more(CallbackInfo info) {
		Mixins.addConfiguration("anything.json");
	}
}

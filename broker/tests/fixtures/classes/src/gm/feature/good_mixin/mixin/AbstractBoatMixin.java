package gm.feature.good_mixin.mixin;

import com.llamalad7.mixinextras.injector.ModifyReturnValue;
import gm.feature.good_mixin.shared.Rules;
import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Constant;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyConstant;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(AbstractBoat.class)
abstract class AbstractBoatMixin {
	@Shadow public abstract float getGroundFriction();

	@Unique private int good_mixin$ticks;

	@ModifyConstant(method = "floatBoat", constant = @Constant(floatValue = 0.9F))
	private float good_mixin$glide(float friction) {
		return Rules.glide(friction);
	}

	@Inject(method = "tick", at = @At(value = "INVOKE", target = "Lnet/minecraft/world/entity/vehicle/boat/AbstractBoat;tickBubbleColumn()V", shift = At.Shift.AFTER))
	private void good_mixin$count(CallbackInfo info) {
		this.good_mixin$ticks++;
	}

	@ModifyReturnValue(method = "getGroundFriction", at = @At("RETURN"))
	private float good_mixin$slippery(float friction) {
		return Math.min(friction, 0.99F);
	}
}

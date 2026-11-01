package gm.companion.mixin;

import gm.companion.Companion;
import net.minecraft.client.Camera;
import net.minecraft.client.DeltaTracker;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Shakes only what's drawn. What the player is looking at comes from where they're facing, which the camera doesn't change. */
@Mixin(Camera.class)
abstract class CameraMixin {
	@Unique
	private final float[] companion$shake = new float[2];

	@Shadow
	private float xRot;

	@Shadow
	private float yRot;

	@Shadow
	protected abstract void setRotation(float yRot, float xRot);

	@Inject(method = "update", at = @At(value = "INVOKE", target = "Lnet/minecraft/client/Camera;alignWithEntity(F)V", shift = At.Shift.AFTER))
	private void companion$shake(DeltaTracker deltaTracker, CallbackInfo info) {
		Companion.host().world().shakeOffset(this.companion$shake);
		if (this.companion$shake[0] != 0 || this.companion$shake[1] != 0) {
			setRotation(this.yRot + this.companion$shake[0], this.xRot + this.companion$shake[1]);
		}
	}
}

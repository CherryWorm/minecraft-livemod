package gm.companion.mixin;

import gm.companion.Companion;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.resources.Identifier;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.util.List;

/** The game works out which screen effects it wants afresh for each frame, so a module's has to be added each time too. */
@Mixin(GameRenderer.class)
abstract class GameRendererMixin {
	@Shadow
	public abstract List<Identifier> getRequestedPostEffects();

	@Inject(method = "update", at = @At("RETURN"))
	private void companion$screenEffects(DeltaTracker deltaTracker, CallbackInfo info) {
		Companion.host().addScreenEffects(getRequestedPostEffects());
	}
}

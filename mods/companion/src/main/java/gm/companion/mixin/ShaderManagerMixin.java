package gm.companion.mixin;

import gm.companion.Companion;
import net.minecraft.client.renderer.PostChain;
import net.minecraft.client.renderer.ShaderManager;
import net.minecraft.resources.Identifier;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

import java.util.Set;

/**
 * The game's answer to a post effect that won't compile is to throw away every resource pack, and that takes a player off a server that
 * requires one. One of this world's screen effects just doesn't appear instead, and the game doesn't try it again.
 */
@Mixin(ShaderManager.class)
abstract class ShaderManagerMixin {
	@Unique
	private Identifier companion$loading;

	@Inject(method = "getPostChain", at = @At("HEAD"))
	private void companion$note(Identifier id, Set<Identifier> targets, CallbackInfoReturnable<PostChain> info) {
		this.companion$loading = id;
	}

	@Inject(method = "getPostChain", at = @At("RETURN"))
	private void companion$done(Identifier id, Set<Identifier> targets, CallbackInfoReturnable<PostChain> info) {
		this.companion$loading = null;
	}

	@Inject(method = "tryTriggerRecovery", at = @At("HEAD"), cancellable = true)
	private void companion$keepPacks(Exception error, CallbackInfo info) {
		if (this.companion$loading != null && this.companion$loading.getNamespace().equals("gm")) {
			info.cancel();
		}
	}

	/** Every compiled shader has just gone, and the pack may now have new ones. */
	@Inject(method = "apply", at = @At("TAIL"))
	private void companion$reloaded(CallbackInfo info) {
		Companion.host().world().resourcesReloaded();
	}
}

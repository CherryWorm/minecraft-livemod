package gm.companion.mixin;

import gm.companion.EffectClient;
import net.minecraft.client.gui.Hud;
import net.minecraft.core.Holder;
import net.minecraft.resources.Identifier;
import net.minecraft.world.effect.MobEffect;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** The game finds an effect's picture by its name in a registry, and this world's aren't in the one on a player's computer. Both the HUD and inventories ask here. */
@Mixin(Hud.class)
abstract class HudMixin {
	@Inject(method = "getMobEffectSprite", at = @At("HEAD"), cancellable = true)
	private static void companion$ownEffectPictures(Holder<MobEffect> effect, CallbackInfoReturnable<Identifier> info) {
		if (effect.value() instanceof EffectClient.ClientEffect own) {
			info.setReturnValue(own.sprite());
		}
	}
}

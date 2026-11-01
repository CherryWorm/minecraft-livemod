package gm.companion.mixin;

import com.mojang.blaze3d.platform.InputConstants;
import gm.companion.Companion;
import net.minecraft.client.KeyboardHandler;
import net.minecraft.client.Minecraft;
import net.minecraft.client.input.KeyEvent;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Fabric only has key events for screens. This only looks, so a module can't get in the way of any key. */
@Mixin(KeyboardHandler.class)
abstract class KeyboardHandlerMixin {
	@Inject(method = "keyPress", at = @At("HEAD"))
	private void companion$keyPressed(long window, int action, KeyEvent event, CallbackInfo info) {
		Minecraft client = Minecraft.getInstance();
		if (action == InputConstants.PRESS && client.player != null && client.gui.screen() == null) {
			Companion.host().keyPressed(event);
		}
	}
}

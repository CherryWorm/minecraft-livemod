package gm.companion.mixin;

import gm.companion.PanelClient;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.MenuScreens;
import net.minecraft.network.chat.Component;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.MenuType;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Where the game chooses a screen for a menu the server opened. A panel is a chest to everything else, so this is the only place that needs to know. */
@Mixin(MenuScreens.class)
abstract class MenuScreensMixin {
	@Inject(method = "create", at = @At("HEAD"), cancellable = true)
	private static <T extends AbstractContainerMenu> void companion$panel(MenuType<T> type, Minecraft client, int containerId, Component title, CallbackInfo info) {
		if (PanelClient.open(type, client, containerId, title)) {
			info.cancel();
		}
	}
}

package gm.companion;

import gm.companion.api.InventoryView;
import gm.companion.api.KeyInput;
import gm.companion.api.MouseInput;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenKeyboardEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenMouseEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.gui.screens.inventory.CreativeModeInventoryScreen;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.input.MouseButtonEvent;

/**
 * Which screens modules may hook, and connects them up. The rule that matters is that what a player types stays theirs: chat,
 * signs, books and the server's password box are all screens, and modules are only told about keys on inventory screens or
 * with none open, and never while a text box has the keyboard.
 */
final class InventoryScreens {
	private InventoryScreens() {}

	static boolean isHookable(Screen screen) {
		return screen instanceof AbstractContainerScreen<?> && !(screen instanceof CreativeModeInventoryScreen);
	}

	private static boolean typingInto(Screen screen) {
		return screen.children().stream().anyMatch(child -> child instanceof EditBox box && box.isFocused());
	}

	/** Whether a module may be told about keys right now. */
	static boolean keysAreSafe() {
		Screen screen = Minecraft.getInstance().gui.screen();
		return screen == null || isHookable(screen) && !typingInto(screen);
	}

	/** The inventory in front of the player, or null if there isn't one that modules may use. */
	static InventoryView current() {
		Minecraft client = Minecraft.getInstance();
		if (client.player == null) {
			return null;
		}
		Screen screen = client.gui.screen();
		if (screen == null) {
			return new ContainerView(null, client.player.inventoryMenu);
		}
		return isHookable(screen) && screen instanceof AbstractContainerScreen<?> container ? new ContainerView(container, container.getMenu()) : null;
	}

	/** A screen's events only last until it next initializes, so this runs every time it does. */
	static void attach(ModuleHost host, Screen screen) {
		if (!isHookable(screen) || !(screen instanceof AbstractContainerScreen<?> container)) {
			return;
		}
		InventoryView view = new ContainerView(container, container.getMenu());
		ScreenEvents.afterExtract(screen).register((shown, graphics, mouseX, mouseY, delta) ->
				host.handleInventory(hooks -> {
					hooks.draw(view, graphics, mouseX, mouseY);
					return false;
				}));
		ScreenMouseEvents.allowMouseClick(screen).register((shown, event) -> !host.handleInventory(hooks -> hooks.mousePressed(view, mouse(event))));
		ScreenMouseEvents.allowMouseDrag(screen).register((shown, event, dragX, dragY) -> !host.handleInventory(hooks -> hooks.mouseDragged(view, mouse(event))));
		ScreenMouseEvents.allowMouseRelease(screen).register((shown, event) -> !host.handleInventory(hooks -> hooks.mouseReleased(view, mouse(event))));
		ScreenMouseEvents.allowMouseScroll(screen).register((shown, mouseX, mouseY, scrollX, scrollY) ->
				!host.handleInventory(hooks -> hooks.mouseScrolled(view, mouse(mouseX, mouseY, -1), scrollY)));
		ScreenKeyboardEvents.allowKeyPress(screen).register((shown, event) ->
				event.isEscape() || typingInto(shown) || !host.handleInventory(hooks -> hooks.keyPressed(view, key(event))));
	}

	private static MouseInput mouse(MouseButtonEvent event) {
		return mouse(event.x(), event.y(), event.button());
	}

	private static MouseInput mouse(double x, double y, int button) {
		Minecraft client = Minecraft.getInstance();
		return new MouseInput(x, y, button, client.hasShiftDown(), client.hasControlDown(), client.hasAltDown());
	}

	static KeyInput key(KeyEvent event) {
		Minecraft client = Minecraft.getInstance();
		return new KeyInput(event.key(), client.hasShiftDown(), client.hasControlDown(), client.hasAltDown());
	}
}

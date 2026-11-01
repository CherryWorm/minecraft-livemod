package gm.feature.hooks;

import gm.companion.api.ClientModule;
import gm.companion.api.InventoryHooks;
import gm.companion.api.InventoryView;
import gm.companion.api.KeyInput;
import gm.companion.api.ModuleContext;
import gm.companion.api.MouseInput;
import net.minecraft.client.gui.GuiGraphicsExtractor;

/**
 * Test fixture: what players asked for, built the way a builder would. Holding shift and dragging across slots moves each one,
 * K moves the first of the main rows, and a mark in the corner proves it can draw on the screen. It claims every key on an
 * inventory screen, to prove that Escape gets through anyway. With no screen open, K swaps the same slot into the first hotbar
 * position, so broker/tests/m16_test.py can see each of these from what really moved.
 */
public final class HooksClient implements ClientModule {
	private static final int FIRST_MAIN_SLOT = 9;
	private static final int MARK_SIZE = 8;
	private static final int MARK_COLOUR = 0xFF11EE77;

	private int lastSlot = -1;

	@Override
	public void enable(ModuleContext context) {
		context.onInventory(new InventoryHooks() {
			@Override
			public void draw(InventoryView inventory, GuiGraphicsExtractor graphics, int mouseX, int mouseY) {
				graphics.fill(0, 0, MARK_SIZE, MARK_SIZE, MARK_COLOUR);
			}

			@Override
			public boolean mousePressed(InventoryView inventory, MouseInput mouse) {
				return moveWhatsUnder(inventory, mouse);
			}

			@Override
			public boolean mouseDragged(InventoryView inventory, MouseInput mouse) {
				return moveWhatsUnder(inventory, mouse);
			}

			@Override
			public boolean mouseReleased(InventoryView inventory, MouseInput mouse) {
				lastSlot = -1;
				return false;
			}

			@Override
			public boolean keyPressed(InventoryView inventory, KeyInput key) {
				if (key.key() == KeyInput.of('K')) {
					inventory.quickMove(FIRST_MAIN_SLOT);
				}
				return true;
			}
		});
		context.onKeyPressed(key -> {
			if (key.key() == KeyInput.of('K') && context.inventory() != null) {
				context.inventory().swapWithHotbar(FIRST_MAIN_SLOT, 0);
			}
		});
	}

	private boolean moveWhatsUnder(InventoryView inventory, MouseInput mouse) {
		if (!mouse.shift() || mouse.button() != MouseInput.LEFT) {
			return false;
		}
		int slot = inventory.slotAt(mouse.x(), mouse.y());
		if (slot != this.lastSlot && !inventory.item(slot).isEmpty()) {
			inventory.quickMove(slot);
		}
		this.lastSlot = slot;
		return true;
	}
}

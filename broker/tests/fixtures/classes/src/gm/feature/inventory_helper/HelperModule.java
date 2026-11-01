package gm.feature.inventory_helper;

import gm.companion.api.ClientModule;
import gm.companion.api.InventoryHooks;
import gm.companion.api.InventoryView;
import gm.companion.api.KeyInput;
import gm.companion.api.ModuleContext;
import gm.companion.api.MouseInput;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.world.item.ItemStack;

/** What a real inventory helper does: reads stacks to decide, draws them, and clicks with the mouse and keys. */
public final class HelperModule implements ClientModule {
	@Override
	public void enable(ModuleContext context) {
		context.onInventory(new InventoryHooks() {
			@Override
			public void draw(InventoryView inventory, GuiGraphicsExtractor graphics, int mouseX, int mouseY) {
				ItemStack hovered = inventory.item(inventory.slotAt(mouseX, mouseY));
				if (!hovered.isEmpty() && hovered.getCount() < hovered.getMaxStackSize()) {
					graphics.item(hovered, mouseX, mouseY);
					graphics.text(Minecraft.getInstance().font, hovered.getHoverName(), mouseX, mouseY - 10, 0xFFFFFFFF);
				}
			}

			@Override
			public boolean mouseDragged(InventoryView inventory, MouseInput mouse) {
				int slot = inventory.slotAt(mouse.x(), mouse.y());
				return mouse.shift() && mouse.button() == MouseInput.LEFT && inventory.isOwn(slot) && inventory.quickMove(slot);
			}

			@Override
			public boolean keyPressed(InventoryView inventory, KeyInput key) {
				for (int slot = 0; slot < inventory.size(); slot++) {
					ItemStack stack = inventory.item(slot);
					if (key.key() == KeyInput.of('R') && ItemStack.isSameItemSameComponents(stack, inventory.carried()) && inventory.accepts(slot, stack)) {
						return inventory.click(slot);
					}
				}
				return false;
			}
		});
		context.onKeyPressed(key -> {
			InventoryView inventory = context.inventory();
			if (inventory != null && context.keyDown(KeyInput.LEFT_SHIFT)) {
				inventory.swapWithHotbar(inventory.size() - 1, inventory.selectedHotbar());
			}
		});
	}
}

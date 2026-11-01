package gm.feature.stack_changing;

import gm.companion.api.ClientModule;
import gm.companion.api.InventoryView;
import gm.companion.api.ModuleContext;

/** Changes a stack in a menu where only the server should, which an inventory view is only meant to let a module look at. */
public final class Bad implements ClientModule {
	@Override
	public void enable(ModuleContext context) {
		InventoryView inventory = context.inventory();
		inventory.item(0).setCount(64);
	}
}

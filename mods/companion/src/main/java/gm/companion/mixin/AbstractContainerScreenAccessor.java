package gm.companion.mixin;

import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.world.inventory.Slot;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;
import org.spongepowered.asm.mixin.gen.Invoker;

/** Where a screen's slots are. A recipe book moves them, so the screen is the only one who knows. */
@Mixin(AbstractContainerScreen.class)
public interface AbstractContainerScreenAccessor {
	@Accessor("leftPos")
	int companion$leftPos();

	@Accessor("topPos")
	int companion$topPos();

	@Invoker("getHoveredSlot")
	Slot companion$slotAt(double mouseX, double mouseY);
}

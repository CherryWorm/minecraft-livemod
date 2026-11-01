package gm.conduit.mixin;

import com.llamalad7.mixinextras.injector.wrapmethod.WrapMethod;
import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.Consumable;
import net.minecraft.world.level.Level;
import org.spongepowered.asm.mixin.Mixin;

/** Everything eaten or drunk ends here. The stack is copied first, because eating the last one leaves it empty. */
@Mixin(Consumable.class)
abstract class ConsumableMixin {
	@WrapMethod(method = "onConsume")
	private ItemStack conduit$tellModules(Level level, LivingEntity user, ItemStack stack, Operation<ItemStack> original) {
		ItemStack eaten = stack.copy();
		ItemStack left = original.call(level, user, stack);
		if (user instanceof ServerPlayer player) {
			ServerModuleHost.instance().fire(events -> events.itemEaten(player, eaten));
		}
		return left;
	}
}

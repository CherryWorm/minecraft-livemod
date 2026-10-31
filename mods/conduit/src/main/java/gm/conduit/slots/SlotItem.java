package gm.conduit.slots;

import eu.pb4.polymer.core.api.item.SimplePolymerItem;
import gm.conduit.api.ItemBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.Level;

/** A blank item. Tool and weapon stats come from components on the stack, set by the recipe that makes it. */
public final class SlotItem extends SimplePolymerItem {
	private final String slotId;

	public SlotItem(Properties properties, String slotId) {
		super(properties);
		this.slotId = slotId;
	}

	@Override
	public InteractionResult use(Level level, Player player, InteractionHand hand) {
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior == null || level.isClientSide()) {
			return super.use(level, player, hand);
		}
		return ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS, () -> behavior.use(level, player, hand));
	}

	@Override
	public InteractionResult useOn(UseOnContext context) {
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior == null || context.getLevel().isClientSide()) {
			return super.useOn(context);
		}
		return ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS, () -> behavior.useOn(context));
	}

	@Override
	public void hurtEnemy(ItemStack stack, LivingEntity target, LivingEntity attacker) {
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior != null && target.level() instanceof ServerLevel) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.hurtEnemy(stack, target, attacker));
		}
		super.hurtEnemy(stack, target, attacker);
	}
}

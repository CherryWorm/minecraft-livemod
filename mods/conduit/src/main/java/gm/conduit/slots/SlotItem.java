package gm.conduit.slots;

import eu.pb4.polymer.core.api.item.SimplePolymerItem;
import gm.conduit.api.ItemBehavior;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.component.DataComponentMap;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;

/** A blank item. Tool and weapon stats come from components on the stack, set by the recipe that makes it. */
public final class SlotItem extends SimplePolymerItem {
	private final String slotId;
	private DataComponentMap releaseComponents;

	public SlotItem(Properties properties, String slotId) {
		super(properties);
		this.slotId = slotId;
	}

	void setReleaseComponents(DataComponentMap components) {
		this.releaseComponents = components == null ? null : DataComponentMap.composite(super.components(), components);
	}

	@Override
	public DataComponentMap components() {
		return this.releaseComponents != null ? this.releaseComponents : super.components();
	}

	@Override
	public InteractionResult use(Level level, Player player, InteractionHand hand) {
		if (player instanceof ServerPlayer serverPlayer && Knowledge.instance().useItem(serverPlayer, player.getItemInHand(hand))) {
			return InteractionResult.SUCCESS;
		}
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior == null || level.isClientSide()) {
			return super.use(level, player, hand);
		}
		return ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS, () -> behavior.use(level, player, hand));
	}

	@Override
	public InteractionResult useOn(UseOnContext context) {
		ItemDefaults.Placement placement = ItemDefaults.placement(this);
		if (placement != null && context.getLevel() instanceof ServerLevel level) {
			return plant(level, context, placement);
		}
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior == null || context.getLevel().isClientSide()) {
			return super.useOn(context);
		}
		return ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS, () -> behavior.useOn(context));
	}

	/** A seed or anything like one: puts its block on top of what was clicked, and uses one up. */
	private static InteractionResult plant(ServerLevel level, UseOnContext context, ItemDefaults.Placement placement) {
		BlockPos below = context.getClickedPos();
		BlockPos spot = below.above();
		BlockState ground = level.getBlockState(below);
		boolean allowedGround = placement.on().isEmpty() ? ground.isSolidRender() : placement.on().contains(ground.getBlock());
		if (context.getClickedFace() != Direction.UP || !allowedGround || !level.getBlockState(spot).canBeReplaced()) {
			return InteractionResult.PASS;
		}
		level.setBlockAndUpdate(spot, placement.block().defaultBlockState());
		level.playSound(null, spot, placement.block().defaultBlockState().getSoundType().getPlaceSound(), SoundSource.BLOCKS, 1.0F, 1.0F);
		context.getItemInHand().consume(1, context.getPlayer());
		return InteractionResult.SUCCESS;
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

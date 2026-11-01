package gm.conduit.slots;

import eu.pb4.polymer.core.api.item.SimplePolymerItem;
import gm.conduit.api.ItemBehavior;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.modules.ServerModuleHost;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.HolderLookup;
import net.minecraft.core.component.DataComponentMap;
import net.minecraft.core.component.DataComponents;
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
	private DataComponentMap baseComponents;

	public SlotItem(Properties properties, String slotId) {
		super(properties);
		this.slotId = slotId;
	}

	/** New stacks read their defaults from the registry holder, so that's what has to change. */
	void setReleaseComponents(DataComponentMap components) {
		var holder = builtInRegistryHolder();
		if (this.baseComponents == null) {
			this.baseComponents = holder.components();
		}
		holder.bindComponents(components == null ? this.baseComponents : DataComponentMap.composite(this.baseComponents, components));
	}

	@Override
	public InteractionResult use(Level level, Player player, InteractionHand hand) {
		if (player instanceof ServerPlayer serverPlayer && Knowledge.instance().useItem(serverPlayer, player.getItemInHand(hand))) {
			return InteractionResult.SUCCESS;
		}
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior != null && !level.isClientSide()) {
			InteractionResult result = ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS, () -> behavior.use(level, player, hand));
			// Unless it's told otherwise, the game goes on holding the stack it called this with, and clears the hand if that's now
			// empty. So a module using up the last of something and putting what it became in the hand would lose it.
			if (result instanceof InteractionResult.Success success && success.heldItemTransformedTo() == null) {
				return success.heldItemTransformedTo(player.getItemInHand(hand));
			}
			if (result != InteractionResult.PASS) {
				return result;
			}
		}
		// This is what eats food, or starts a timed use.
		return super.use(level, player, hand);
	}

	@Override
	public ItemStack finishUsingItem(ItemStack stack, Level level, LivingEntity user) {
		if (!ItemDefaults.isTimedUse(this)) {
			return super.finishUsingItem(stack, level, user);
		}
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior != null && level instanceof ServerLevel) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.finishUsing(stack, level, user));
		}
		// To a client it's like food, so it has just taken one away, and the server has nothing new to tell it unless it's asked to.
		if (user instanceof ServerPlayer player) {
			player.inventoryMenu.sendAllDataToRemote();
		}
		return stack;
	}

	/** What decides how it's drawn, which a client has to be told, as it's only ever told what it needs to know. */
	@Override
	public void modifyBasePolymerItemStack(ItemStack out, ItemStack stack, PacketContext context, HolderLookup.Provider lookup) {
		super.modifyBasePolymerItemStack(out, stack, context, lookup);
		if (stack.has(DataComponents.CUSTOM_MODEL_DATA)) {
			out.set(DataComponents.CUSTOM_MODEL_DATA, stack.get(DataComponents.CUSTOM_MODEL_DATA));
		}
		if (stack.has(DataComponents.LODESTONE_TRACKER)) {
			out.set(DataComponents.LODESTONE_TRACKER, stack.get(DataComponents.LODESTONE_TRACKER));
		}
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
	public InteractionResult interactLivingEntity(ItemStack stack, Player player, LivingEntity target, InteractionHand hand) {
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior == null || player.level().isClientSide()) {
			return super.interactLivingEntity(stack, player, target, hand);
		}
		return ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS, () -> behavior.useOnEntity(stack, player, target, hand));
	}

	@Override
	public boolean mineBlock(ItemStack stack, Level level, BlockState state, BlockPos pos, LivingEntity miner) {
		ItemBehavior behavior = ServerModuleHost.instance().itemBehavior(this.slotId);
		if (behavior != null && level instanceof ServerLevel) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.mineBlock(stack, level, state, pos, miner));
		}
		return super.mineBlock(stack, level, state, pos, miner);
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

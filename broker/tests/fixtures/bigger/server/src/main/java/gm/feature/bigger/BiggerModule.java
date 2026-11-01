package gm.feature.bigger;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.MachineAttempt;
import gm.conduit.api.MachineBehavior;
import gm.conduit.api.MenuBehavior;
import gm.conduit.api.MenuView;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.mobs.SlotMob;
import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

import java.util.List;

/** Test fixture: says in chat whenever one of its hooks runs, so broker/tests/m17_test.py can read what really happened on a real client. */
public final class BiggerModule implements ServerModule {
	private static final int FIRST_OUTPUT = 3;
	private ServerModuleContext context;

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal("BIG " + text), false);
	}

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.subscribe("bigger/finished", message -> say("heard " + message.getIntOr("seconds", 0)));
		context.bindMachine("big_kiln", new MachineBehavior() {
			@Override
			public void tick(SlotBlockEntity machine) {
				if (!machine.getItem(FIRST_OUTPUT).isEmpty() || !machine.getItem(FIRST_OUTPUT + 1).isEmpty()) {
					return;
				}
				List<ItemStack> inputs = List.of(machine.getItem(0), machine.getItem(1));
				MachineAttempt attempt = context.attemptRecipe(null, "bigger/big_kiln", inputs);
				if (attempt.succeeded()) {
					attempt.consume(inputs);
					machine.setItem(FIRST_OUTPUT, attempt.outputs().get(0).copy());
					machine.setItem(FIRST_OUTPUT + 1, attempt.outputs().get(1).copy());
					say("made " + attempt.recipe() + " taking " + attempt.takes().get(0).getCount());
				}
			}

			@Override
			public boolean accepts(SlotBlockEntity machine, int slot, ItemStack stack) {
				return !stack.is(Items.DIRT);
			}
		});
		context.bindBlock("big_kiln", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level.getBlockEntity(pos) instanceof SlotBlockEntity machine && player instanceof ServerPlayer serverPlayer) {
					machine.openMenu(serverPlayer, Component.literal("Big Kiln"));
				}
				return InteractionResult.SUCCESS;
			}
		});
		context.bindMachine("big_gauge", machine -> {
			if (machine.data().contains("value")) {
				machine.show("walk", machine.data().getFloatOr("value", 0.0F));
			}
		});
		context.bindBlock("big_button", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				context.openMenu((ServerPlayer) player, Component.literal("Big Menu"), 1, new MenuBehavior() {
					private int clicks;

					@Override
					public void draw(MenuView menu) {
						menu.set(3, new ItemStack(Items.DIAMOND, 1 + this.clicks));
					}

					@Override
					public void clicked(MenuView menu, int slot, boolean rightClick, boolean shift) {
						this.clicks++;
						say("button " + slot + " right " + rightClick + " shift " + shift);
					}

					@Override
					public void closed(MenuView menu) {
						say("menu closed after " + this.clicks);
					}
				});
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("big_tool", new ItemBehavior() {
			@Override
			public void finishUsing(ItemStack stack, Level level, LivingEntity user) {
				say("finished using " + stack.getCount());
				CompoundTag message = new CompoundTag();
				message.putInt("seconds", 1);
				context.publish("finished", message);
			}
		});
		context.bindItem("big_book", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				context.openBook((ServerPlayer) player, "Big Book", List.of(Component.literal("First page"), Component.literal("Second page")));
				say("book opened, natural " + context.isNatural(level, player.blockPosition().below(100)) + " " + context.isNatural(level, player.blockPosition().below()));
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("big_lens", new ItemBehavior() {
			@Override
			public InteractionResult useOn(UseOnContext use) {
				context.examine((ServerPlayer) use.getPlayer(), use.getLevel().getBlockState(use.getClickedPos()));
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("big_paint", new ItemBehavior() {
			@Override
			public InteractionResult useOnEntity(ItemStack stack, Player player, LivingEntity target, InteractionHand hand) {
				if (hand == InteractionHand.MAIN_HAND && target instanceof SlotMob mob) {
					mob.setTint(0xFF0000);
					say("painted " + Integer.toHexString(mob.tint()));
				}
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("big_shrink", new ItemBehavior() {
			@Override
			public InteractionResult useOnEntity(ItemStack stack, Player player, LivingEntity target, InteractionHand hand) {
				if (hand == InteractionHand.MAIN_HAND && target instanceof SlotMob mob) {
					mob.makeBaby(6);
					say("shrunk baby " + mob.isBaby() + " height " + mob.getBbHeight());
				}
				return InteractionResult.SUCCESS;
			}
		});
	}
}

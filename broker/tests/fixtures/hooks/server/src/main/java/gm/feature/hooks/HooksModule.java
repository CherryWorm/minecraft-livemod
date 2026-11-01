package gm.feature.hooks;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.MachineBehavior;
import gm.conduit.api.MobBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.WorldEvents;
import gm.conduit.mobs.SlotMob;
import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

/** Test fixture: says in chat whenever one of its hooks runs, so broker/tests/m16_test.py can read what really happened on a real client. */
public final class HooksModule implements ServerModule {
	private ServerModuleContext context;

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal("HOOK " + text), false);
	}

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.listen(new WorldEvents() {
			@Override
			public void blockBroken(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state, BlockEntity blockEntity) {
				if (state.is(context.block("hook_block"))) {
					say("broke it, and the spot now holds " + level.getBlockState(pos).getBlock().getName().getString());
				}
			}

			@Override
			public void mobKilled(LivingEntity mob, DamageSource source) {
				if (mob.getType() == context.mob("hook_mob")) {
					say("killed by " + source.getMsgId());
				}
			}

			@Override
			public void itemEaten(ServerPlayer player, ItemStack stack) {
				say("ate " + stack.getCount() + " of ours " + stack.is(context.item("hook_food")));
			}

			@Override
			public void playerJoined(ServerPlayer player) {
				say("joined " + player.getName().getString());
			}

			@Override
			public void knowledgeLearned(ServerPlayer player, String entry, String title) {
				say("learned " + entry + " called " + title);
			}

			@Override
			public void blockExamined(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state) {
				say("examined block " + state.is(context.block("hook_block")));
			}

			@Override
			public void mobExamined(ServerPlayer player, Entity mob) {
				say("examined mob " + (mob.getType() == context.mob("hook_mob")));
			}
		});
		context.bindBlock("hook_block", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				context.playSound("hook_chime", level, pos, 1.0F, 1.0F);
				say("chimed");
				return InteractionResult.SUCCESS;
			}

			@Override
			public void removed(BlockState state, ServerLevel level, BlockPos pos) {
				say("removed " + state.is(context.block("hook_block")));
			}
		});
		context.bindMachine("hook_machine", new MachineBehavior() {
			@Override
			public void tick(SlotBlockEntity machine) {
				machine.data().putInt("held", 7);
			}

			@Override
			public void removed(SlotBlockEntity machine) {
				say("machine held " + machine.data().getIntOr("held", 0));
			}
		});
		context.bindMob("hook_mob", new MobBehavior() {
			@Override
			public InteractionResult interact(SlotMob mob, Player player, InteractionHand hand) {
				if (hand != InteractionHand.MAIN_HAND || !player.getMainHandItem().is(context.item("hook_food"))) {
					return InteractionResult.PASS;
				}
				player.getMainHandItem().shrink(1);
				say("fed");
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("hook_token", new ItemBehavior() {
			@Override
			public InteractionResult useOnEntity(ItemStack stack, Player player, LivingEntity target, InteractionHand hand) {
				say("token used on " + (target.getType() == context.mob("hook_mob")));
				return InteractionResult.SUCCESS;
			}

			@Override
			public void mineBlock(ItemStack stack, Level level, BlockState state, BlockPos pos, LivingEntity miner) {
				say("token mined " + state.is(context.block("hook_block")));
			}
		});
	}
}

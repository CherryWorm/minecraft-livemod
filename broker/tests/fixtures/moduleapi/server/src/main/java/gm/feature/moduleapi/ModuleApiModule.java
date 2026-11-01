package gm.feature.moduleapi;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.MachineBehavior;
import gm.conduit.api.MobBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.WorldEvents;
import gm.conduit.mobs.SlotMob;
import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.util.RandomSource;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

/** Says everything it hears in chat, so a test client can tell what happened on the server. */
public final class ModuleApiModule implements ServerModule {
	private static final int LAMP_LOW = 9;
	private static final int LAMP_HIGH = 14;
	private ServerModuleContext context;
	private boolean postOn = true;

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal("API " + text), false);
	}

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		bindPlacing();
		bindRedstone();
		bindLight();
		bindStatue();
		bindKiln();
		bindMobs();
		context.listen(new WorldEvents() {
			@Override
			public float damage(LivingEntity target, DamageSource source, float amount) {
				if (target.getType() == context.mob("api_ox") && amount > 0) {
					say("ox would take " + amount);
					return target.getMainHandItem().isEmpty() && target.getHealth() >= 6 ? 0 : 1;
				}
				if (target instanceof ServerPlayer && target.hasItemInSlot(EquipmentSlot.HEAD) && amount > 0) {
					say("player would take " + amount);
					return amount / 2;
				}
				return amount;
			}

			@Override
			public boolean survives(LivingEntity target, DamageSource source, float amount) {
				if (target.getType() == context.mob("api_calf") && !target.getTags().contains("dead_for_real")) {
					say("calf cheats death from " + amount);
					target.addTag("dead_for_real");
					target.setHealth(3);
					return true;
				}
				return false;
			}

			@Override
			public double knockback(LivingEntity target, DamageSource source, double power) {
				if (target.getType() == context.mob("api_calf")) {
					say("calf pushed " + power);
					return power * 5;
				}
				return power;
			}

			@Override
			public void blockPlaced(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state, ItemStack stack) {
				say("anything placed " + state.getBlock().getName().getString() + " from " + stack.getCount());
			}

			@Override
			public boolean canBreak(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state) {
				if (state.is(net.minecraft.world.level.block.Blocks.BEDROCK)) {
					return true;
				}
				boolean allowed = !state.is(net.minecraft.world.level.block.Blocks.GOLD_BLOCK);
				if (!allowed) {
					say("no breaking gold");
				}
				return allowed;
			}
		});
	}

	private void bindMobs() {
		this.context.bindMob("api_ox", new MobBehavior() {
			@Override
			public InteractionResult interact(SlotMob mob, Player player, InteractionHand hand) {
				if (hand != InteractionHand.MAIN_HAND) {
					return InteractionResult.PASS;
				}
				boolean first = !mob.isWalking();
				BlockPos goal = mob.blockPosition().east(first ? 4 : 2);
				say("ox sets off for " + goal.toShortString());
				mob.walkTo(goal, 1.5, arrived -> say("ox " + (arrived ? "arrived" : "gave up") + " at " + mob.blockPosition().closerThan(goal, 2)));
				return InteractionResult.SUCCESS;
			}
		});
		this.context.bindMob("api_bat", new MobBehavior() {
			@Override
			public InteractionResult interact(SlotMob mob, Player player, InteractionHand hand) {
				if (hand == InteractionHand.MAIN_HAND) {
					say("bat flying " + mob.isFlying() + " at " + mob.getY());
					BlockPos goal = mob.blockPosition().above(5);
					mob.walkTo(goal, 2.0, arrived -> say("bat " + (arrived ? "arrived" : "gave up") + " in the air " + mob.isNoGravity()));
				}
				return InteractionResult.SUCCESS;
			}
		});
	}

	private void bindPlacing() {
		this.context.bindBlock("api_gate", new BlockBehavior() {
			@Override
			public boolean canPlace(BlockPlaceContext place) {
				boolean allowed = Math.floorMod(place.getClickedPos().getX(), 2) == 0;
				say(allowed ? "gate may go here" : "gate can't go here");
				return allowed;
			}

			@Override
			public void placed(BlockState state, Level level, BlockPos pos, LivingEntity by, ItemStack stack) {
				say("gate placed by " + (by == null ? "nobody" : by.getName().getString()) + " with " + stack.getHoverName().getString());
			}

			@Override
			public boolean canBreak(BlockState state, Level level, BlockPos pos, Player player) {
				boolean allowed = player.getMainHandItem().is(ModuleApiModule.this.context.item("api_token"));
				say(allowed ? "gate gives way" : "gate won't break");
				return allowed;
			}
		});
	}

	private void bindRedstone() {
		this.context.bindBlock("api_post", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				ModuleApiModule.this.postOn = !ModuleApiModule.this.postOn;
				ModuleApiModule.this.context.redstoneChanged(level, pos);
				say("post " + (ModuleApiModule.this.postOn ? "on" : "off"));
				return InteractionResult.SUCCESS;
			}

			@Override
			public int redstone(BlockState state, Level level, BlockPos pos, Direction side) {
				return ModuleApiModule.this.postOn && side == Direction.EAST ? 15 : 0;
			}

			@Override
			public void scheduledTick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {
				say("post waited");
			}
		});
	}

	private void bindLight() {
		this.context.bindBlock("api_lamp", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				int light = state.getLightEmission() == LAMP_HIGH ? 0 : LAMP_HIGH;
				ModuleApiModule.this.context.setLight(level, pos, light);
				say("lamp now " + light);
				return InteractionResult.SUCCESS;
			}
		});
	}

	private void bindStatue() {
		this.context.bindMachine("api_statue", new MachineBehavior() {
			@Override
			public void tick(SlotBlockEntity machine) {}
		});
		this.context.bindBlock("api_statue", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level.getBlockEntity(pos) instanceof SlotBlockEntity machine) {
					boolean moved = machine.movePart("head", 0, 1, 0);
					boolean tinted = machine.tintPart("tail", 0xFF0000);
					boolean scaled = machine.scalePart("tail", 2, 2, 2);
					boolean turned = machine.turnPart("body", 0, 45, 0);
					boolean missing = machine.movePart("wings", 0, 1, 0);
					machine.setLight(12);
					say("statue moved " + moved + " tinted " + tinted + " scaled " + scaled + " turned " + turned + " wings " + missing + " facing " + machine.facing());
				}
				return InteractionResult.SUCCESS;
			}
		});
	}

	private void bindKiln() {
		this.context.bindMachine("api_kiln", new MachineBehavior() {
			private int heard = -1;

			@Override
			public void tick(SlotBlockEntity machine) {
				int power = machine.redstoneInput();
				if (power != this.heard) {
					this.heard = power;
					say("kiln power " + power);
				}
			}

			@Override
			public boolean canTake(SlotBlockEntity machine, int slot, Player player) {
				boolean allowed = !machine.getItem(slot).is(ModuleApiModule.this.context.item("api_lamp").asItem());
				if (!allowed) {
					say("kiln still busy");
				}
				return allowed;
			}

			@Override
			public void outputTaken(SlotBlockEntity machine, int slot, ItemStack stack, Player player) {
				say("kiln gave " + stack.getCount() + " of " + stack.getHoverName().getString() + " to " + player.getName().getString() + " from slot " + slot);
			}
		});
		this.context.bindBlock("api_kiln", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level.getBlockEntity(pos) instanceof SlotBlockEntity machine && player instanceof ServerPlayer serverPlayer) {
					machine.openMenu(serverPlayer, Component.literal("Api Kiln"));
				}
				return InteractionResult.SUCCESS;
			}

			@Override
			public void neighborChanged(BlockState state, Level level, BlockPos pos, Block neighbor) {
				say("kiln neighbour " + neighbor.getName().getString() + " power " + level.getBestNeighborSignal(pos));
			}
		});
	}
}

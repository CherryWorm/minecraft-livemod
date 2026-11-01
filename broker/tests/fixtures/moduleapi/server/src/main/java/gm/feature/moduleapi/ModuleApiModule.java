package gm.feature.moduleapi;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.EffectBehavior;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.MachineAttempt;
import gm.conduit.api.MachineBehavior;
import gm.conduit.api.MobBehavior;
import gm.conduit.api.PlayerKey;
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
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.phys.BlockHitResult;

import java.util.ArrayList;
import java.util.List;

/** Says everything it hears in chat, so a test client can tell what happened on the server. */
public final class ModuleApiModule implements ServerModule {
	private static final int LAMP_LOW = 9;
	private static final int LAMP_HIGH = 14;
	private ServerModuleContext context;
	private boolean postOn = true;

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal("API " + text), false);
	}

	/** This world's names are only in the pack, so to the server they're keys. */
	private String name(ItemStack stack) {
		for (String item : List.of("api_token", "api_big", "api_ingot", "api_gate", "api_lamp")) {
			if (stack.is(this.context.item(item))) {
				return item;
			}
		}
		return stack.isEmpty() ? "nothing" : stack.getItem().toString();
	}

	private String name(Entity entity) {
		return entity.getType() == this.context.mob("api_calf") ? "calf" : entity.getName().getString();
	}

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		bindPlacing();
		bindRedstone();
		bindLight();
		bindStatue();
		bindKiln();
		bindGauge();
		bindMobs();
		bindItems();
		context.bindBlock("api_brine", new BlockBehavior() {
			private boolean said;

			@Override
			public void entityInside(BlockState state, Level level, BlockPos pos, Entity entity) {
				if (!this.said && entity instanceof Player) {
					this.said = true;
					say("in the brine, in water " + entity.isInWater() + " is it " + level.getFluidState(pos).is(ModuleApiModule.this.context.fluid("api_brine")));
				}
			}
		});
		context.bindEffect("api_blessed", new EffectBehavior() {
			private int ticks;

			@Override
			public void tick(LivingEntity entity, int level) {
				if (++this.ticks == 10) {
					say("blessed tick level " + level + " on " + name(entity));
				}
			}

			@Override
			public void started(LivingEntity entity, int level) {
				this.ticks = 0;
				say("blessed started level " + level + " has it " + entity.hasEffect(ModuleApiModule.this.context.effect("api_blessed")));
			}

			@Override
			public void ended(LivingEntity entity) {
				say("blessed ended on " + name(entity));
			}
		});
		// It counts every time this module starts, so a test can tell it's been replaced, and that this came through.
		context.state().putInt("started", context.state().getIntOr("started", 0) + 1);
		say("state started " + context.state().getIntOr("started", 0) + " uses " + context.state().getIntOr("uses", 0));
		context.listen(new WorldEvents() {
			@Override
			public void playerJumped(ServerPlayer player) {
				say("jumped " + player.getName().getString());
			}

			@Override
			public void keyPressed(ServerPlayer player, PlayerKey key) {
				say("pressed " + key);
			}

			@Override
			public void keyReleased(ServerPlayer player, PlayerKey key) {
				say("released " + key);
			}

			@Override
			public void keyDoubleTapped(ServerPlayer player, PlayerKey key) {
				say("double tapped " + key);
			}

			@Override
			public void chunkLoaded(ServerLevel level, LevelChunk chunk, boolean isNew) {
				if (chunk.getPos().x() == 625 && chunk.getPos().z() == 625) {
					say("chunk loaded new " + isNew);
				}
			}

			@Override
			public void chunkUnloaded(ServerLevel level, LevelChunk chunk) {
				if (chunk.getPos().x() == 625 && chunk.getPos().z() == 625) {
					say("chunk unloaded");
				}
			}

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
				say("anything placed " + name(stack) + " from " + stack.getCount());
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
			private boolean said;

			@Override
			public void tick(SlotMob mob) {
				if (!this.said && mob.isWalking() && mob.walkAnimation.isMoving()) {
					this.said = true;
					say("ox legs moving");
				}
			}

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

	private void bindItems() {
		this.context.bindItem("api_cell", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				ItemStack stack = player.getItemInHand(hand);
				float bar = ModuleApiModule.this.context.bar(stack);
				float next = bar <= 0 ? 1 : bar - 0.25F;
				ModuleApiModule.this.context.setBar(stack, next);
				say("cell went from " + bar + " to " + next);
				return InteractionResult.SUCCESS;
			}
		});
		this.context.bindBlock("api_bench", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level.getBlockEntity(pos) instanceof SlotBlockEntity bench && player instanceof ServerPlayer serverPlayer) {
					bench.openMenu(serverPlayer, Component.literal("Api Bench"));
				}
				return InteractionResult.SUCCESS;
			}
		});
		this.context.bindMachine("api_bench", new MachineBehavior() {
			private List<ItemStack> grid(SlotBlockEntity bench) {
				List<ItemStack> grid = new ArrayList<>();
				for (int slot = 0; slot < 16; slot++) {
					grid.add(bench.getItem(slot));
				}
				return grid;
			}

			@Override
			public void tick(SlotBlockEntity bench) {
				MachineAttempt attempt = ModuleApiModule.this.context.attemptRecipe(null, "api_bench", grid(bench), 4);
				ItemStack shown = attempt.succeeded() ? attempt.output().copy() : ItemStack.EMPTY;
				if (!ItemStack.matches(shown, bench.getItem(16))) {
					bench.setItem(16, shown);
					say("bench offers " + shown.getCount() + " " + name(shown));
				}
			}

			@Override
			public void outputTaken(SlotBlockEntity bench, int slot, ItemStack stack, Player player) {
				List<ItemStack> grid = grid(bench);
				ModuleApiModule.this.context.attemptRecipe(null, "api_bench", grid, 4).consume(grid);
				bench.setChanged();
				say("bench made " + name(stack));
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
				say("gate placed by " + (by == null ? "nobody" : by.getName().getString()) + " with " + name(stack));
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
				ModuleApiModule.this.context.state().putInt("uses", ModuleApiModule.this.context.state().getIntOr("uses", 0) + 1);
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

	private void bindGauge() {
		this.context.bindMachine("api_gauge", new MachineBehavior() {
			@Override
			public void tick(SlotBlockEntity machine) {}
		});
		this.context.bindBlock("api_gauge", new BlockBehavior() {
			private boolean high;

			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level.getBlockEntity(pos) instanceof SlotBlockEntity machine) {
					this.high = !this.high;
					machine.show("walk", this.high ? 0.75F : 0.25F);
					machine.show("idle", 0.5F);
					say("gauge at " + this.high);
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
				say("kiln gave " + stack.getCount() + " of " + name(stack) + " to " + player.getName().getString() + " from slot " + slot);
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

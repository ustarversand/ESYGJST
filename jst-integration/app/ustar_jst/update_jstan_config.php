<?php
// 更新聚水潭配置
$config = json_encode([
    'status' => '1',
    'shop_id' => '20941412',
    'app_key' => 'd561deb348274f1ba3505ec4578870fd',
    'app_secret' => '84ad2c023b9b49378b1161ea569e383c',
    'access_token' => 'cfda23ff97664494bc6fc5ab46f8ea48'
]);

$sql = "UPDATE ecs_config SET config = '$config' WHERE code = 'jstan.erp'";

$link = mysqli_connect('192.168.178.26', 'root', 'Ecshop@2026!', 'ecshop_renzheng');
if (!$link) {
    die("连接失败: " . mysqli_connect_error());
}

if (mysqli_query($link, $sql)) {
    echo "配置更新成功!\n";
    
    // 验证
    $result = mysqli_query($link, "SELECT config FROM ecs_config WHERE code = 'jstan.erp'");
    $row = mysqli_fetch_assoc($result);
    echo "当前配置: " . $row['config'] . "\n";
} else {
    echo "更新失败: " . mysqli_error($link);
}

mysqli_close($link);
?>